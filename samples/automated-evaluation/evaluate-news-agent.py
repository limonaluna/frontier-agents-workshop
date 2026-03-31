# Copyright (c) Microsoft. All rights reserved.
"""
Automated Evaluation of a News Agent

Runs the Hacker News agent on a test query, then evaluates the response using
the Azure AI Evaluation SDK (azure-ai-evaluation).  Evaluators span three categories:

  Quality:       Groundedness, Coherence, Fluency, Relevance
  Agent:         Intent Resolution, Tool Call Accuracy
  Risk & Safety: Content Safety (violence, self-harm, sexual, hate/unfairness)

Evaluation scores are emitted as OTEL span events to Application Insights and
optionally pushed to the Foundry evaluation dashboard.

Usage:
    python samples/automated-evaluation/evaluate-news-agent.py
"""

import sys
from pathlib import Path

# Add project root so we can import samples.shared
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncio
import json
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, List, Literal

import httpx
from dotenv import load_dotenv
from pydantic import Field

# Suppress verbose Azure SDK / OTEL exporter logs
for _logger_name in [
    "azure", "azure.core", "azure.monitor",
    "azure.ai.evaluation", "opentelemetry", "urllib3",
]:
    logging.getLogger(_logger_name).setLevel(logging.WARNING)
# Credential-chain warnings are extremely noisy — suppress completely
logging.getLogger("azure.identity").setLevel(logging.ERROR)

from agent_framework import Agent
from agent_framework.observability import get_tracer, configure_otel_providers
from opentelemetry import context as otel_context, trace
from opentelemetry.trace import SpanKind
from samples.shared.model_client import create_chat_client

from azure.ai.evaluation import (
    AzureOpenAIModelConfiguration,
    CoherenceEvaluator,
    ContentSafetyEvaluator,
    EvaluatorConfig,
    FluencyEvaluator,
    GroundednessEvaluator,
    IntentResolutionEvaluator,
    RelevanceEvaluator,
    ToolCallAccuracyEvaluator,
    evaluate,
)

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Test query
# ---------------------------------------------------------------------------

TEST_QUERY = "Give me a brief summary of the current top 3 Hacker News stories."

# ---------------------------------------------------------------------------
# Hacker News tools (reused from the observability sample)
# ---------------------------------------------------------------------------

def get_hackernews_story_ids(
    list_type: Annotated[
        Literal["top", "new", "best"],
        Field(description="Which Hacker News list to fetch: 'top', 'new', or 'best'."),
    ] = "top",
    limit: Annotated[
        int,
        Field(description="Maximum number of story IDs to return (1-50).", ge=1, le=50),
    ] = 10,
) -> List[int]:
    """Get a list of recent Hacker News story IDs using the Firebase API."""
    base = "https://hacker-news.firebaseio.com/v0"
    path_map = {"top": "topstories", "new": "newstories", "best": "beststories"}
    url = f"{base}/{path_map[list_type]}.json"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params={"print": "pretty"})
        resp.raise_for_status()
        ids = resp.json() or []
    return ids[:limit]


def get_hackernews_story(
    story_id: Annotated[int, Field(description="The Hacker News story ID to retrieve.")],
) -> dict:
    """Get the full JSON details of a Hacker News story by ID."""
    url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params={"print": "pretty"})
        resp.raise_for_status()
        return resp.json() or {}


# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------

def create_news_agent() -> Agent:
    model_name = os.environ.get("COMPLETION_DEPLOYMENT_NAME") or os.environ.get("MEDIUM_DEPLOYMENT_MODEL_NAME")
    client = create_chat_client(model_name)
    return Agent(
        client=client,
        instructions=(
            "You are a helpful news assistant that uses the provided tools "
            "to fetch and summarize Hacker News stories. When asked about "
            "Hacker News, first fetch relevant story IDs, then retrieve "
            "their details and provide concise summaries."
        ),
        tools=[get_hackernews_story_ids, get_hackernews_story],
    )


# ---------------------------------------------------------------------------
# Tool definitions (used by agent evaluators to assess tool usage)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS = [
    {
        "name": "get_hackernews_story_ids",
        "description": "Get a list of recent Hacker News story IDs using the Firebase API.",
        "parameters": {
            "type": "object",
            "properties": {
                "list_type": {
                    "type": "string",
                    "enum": ["top", "new", "best"],
                    "description": "Which Hacker News list to fetch: 'top', 'new', or 'best'."
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of story IDs to return (1-50).",
                    "minimum": 1,
                    "maximum": 50
                }
            }
        }
    },
    {
        "name": "get_hackernews_story",
        "description": "Get the full JSON details of a Hacker News story by ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "story_id": {
                    "type": "integer",
                    "description": "The Hacker News story ID to retrieve."
                }
            },
            "required": ["story_id"]
        }
    }
]


# ---------------------------------------------------------------------------
# Evaluator setup
# ---------------------------------------------------------------------------

def create_evaluators() -> dict:
    """Create the suite of quality, agent, and safety evaluators."""
    judge_model = os.environ.get("COMPLETION_DEPLOYMENT_NAME") or os.environ.get("MEDIUM_DEPLOYMENT_MODEL_NAME", "gpt-4.1-mini")

    config: dict = dict(
        azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT"),
        api_version="2024-12-01-preview",
        azure_deployment=judge_model,
    )
    api_key = os.environ.get("AZURE_OPENAI_API_KEY")
    if api_key:
        config["api_key"] = api_key

    model_config = AzureOpenAIModelConfiguration(**config)

    # Share a SINGLE credential across all evaluators so parallel threads
    # don't each spawn their own `az account get-access-token` subprocess.
    from azure.identity import DefaultAzureCredential
    credential = DefaultAzureCredential()
    # Pre-warm: acquire a token now so the cache is populated before threads start.
    credential.get_token("https://cognitiveservices.azure.com/.default")

    evaluators = {
        # Quality evaluators
        "groundedness": GroundednessEvaluator(model_config=model_config, credential=credential),
        "coherence": CoherenceEvaluator(model_config=model_config, credential=credential),
        "fluency": FluencyEvaluator(model_config=model_config, credential=credential),
        "relevance": RelevanceEvaluator(model_config=model_config, credential=credential),
        # Agent evaluators
        "intent_resolution": IntentResolutionEvaluator(model_config=model_config, credential=credential),
        "tool_call_accuracy": ToolCallAccuracyEvaluator(model_config=model_config, credential=credential),
    }

    # Risk & Safety evaluators require a Foundry project endpoint
    foundry_project = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if foundry_project:
        evaluators["content_safety"] = ContentSafetyEvaluator(
            credential=credential, azure_ai_project=foundry_project
        )
        print(f"  Content safety evaluator enabled (project: {foundry_project})")
    else:
        print("  No FOUNDRY_PROJECT_ENDPOINT set — content safety evaluator skipped.")

    return evaluators


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

async def run_evaluation():
    print("=" * 60)
    print("AUTOMATED EVALUATION — News Agent")
    print("=" * 60)

    # --- Configure observability ---
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    exporters = []
    if connection_string:
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter, AzureMonitorMetricExporter
        exporters.append(AzureMonitorTraceExporter(connection_string=connection_string))
        exporters.append(AzureMonitorMetricExporter(connection_string=connection_string))
        print("Application Insights exporters configured.")

    configure_otel_providers(
        exporters=exporters if exporters else None,
        enable_sensitive_data=True,
    )
    tracer = get_tracer()

    agent = create_news_agent()
    evaluators = create_evaluators()

    # --- Run agent query ---
    print(f"\nQuery: {TEST_QUERY}")
    start = time.time()
    session = agent.create_session()
    span = tracer.start_span("eval:query", kind=SpanKind.INTERNAL)
    span.set_attribute("eval.query", TEST_QUERY)
    ctx = trace.set_span_in_context(span)
    token = otel_context.attach(ctx)
    response = await agent.run(TEST_QUERY, session=session)
    otel_context.detach(token)
    agent_text = response.text
    elapsed = time.time() - start
    print(f"Agent responded in {elapsed:.1f}s ({len(agent_text)} chars)")

    # --- Extract context and tool calls from response ---
    context_parts, tool_calls = [], []
    for msg in response.to_dict().get("messages", []):
        role = msg.get("role", "")
        if role == "tool":
            for content in msg.get("contents", []):
                for item in content.get("items", []):
                    text = item.get("text", "")
                    if text:
                        context_parts.append(text)
        elif role == "assistant":
            for content in msg.get("contents", []):
                if content.get("type") == "function_call":
                    tool_calls.append({
                        "type": "tool_call",
                        "name": content.get("name", ""),
                        "arguments": content.get("arguments", "{}"),
                        "tool_call_id": content.get("call_id", ""),
                    })
    context = "\n".join(context_parts) if context_parts else agent_text

    # --- Evaluate (all evaluators in parallel via thread pool) ---
    print("Evaluating...")
    loop = asyncio.get_event_loop()

    def run_evaluator(name, evaluator):
        try:
            if name == "groundedness":
                result = evaluator(query=TEST_QUERY, response=agent_text, context=context)
            elif name == "tool_call_accuracy":
                if not tool_calls:
                    return name, "N/A", "No tool calls in response"
                result = evaluator(query=TEST_QUERY, tool_calls=tool_calls, tool_definitions=TOOL_DEFINITIONS)
            elif name == "intent_resolution":
                result = evaluator(query=TEST_QUERY, response=agent_text, tool_definitions=TOOL_DEFINITIONS)
            elif name == "content_safety":
                result = evaluator(query=TEST_QUERY, response=agent_text)
                cs_score = "pass" if result.get("content_safety_defect_rate", 0) == 0 else "fail"
                return name, cs_score, f"defect_rate={result.get('content_safety_defect_rate', 'N/A')}"
            else:
                result = evaluator(query=TEST_QUERY, response=agent_text)

            raw = result.get(name)
            if raw is None or (isinstance(raw, float) and math.isnan(raw)):
                score = 0
            elif isinstance(raw, str):
                score = raw
            else:
                score = float(raw)
            return name, score, result.get(f"{name}_reason", "")
        except Exception as e:
            return name, None, str(e)

    with ThreadPoolExecutor(max_workers=len(evaluators)) as executor:
        futures = {name: loop.run_in_executor(executor, run_evaluator, name, ev)
                   for name, ev in evaluators.items()}
        eval_results = await asyncio.gather(*futures.values())

    scores, reasons = {}, {}
    for res in eval_results:
        scores[res[0]] = res[1]
        reasons[res[0]] = res[2]

    # --- Emit evaluation scores as OTEL span attributes & events ---
    for k, v in scores.items():
        if isinstance(v, (int, float)):
            span.set_attribute(f"eval.{k}", v)
    span.add_event("evaluation_scores", attributes={
        k: (str(v) if not isinstance(v, (int, float)) else v)
        for k, v in scores.items() if v is not None
    })
    span.end()

    total_time = time.time() - start

    # --- Summary ---
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)
    for name, score in scores.items():
        marker = f"{score}/5" if isinstance(score, (int, float)) else (score or "ERR")
        reason = reasons.get(name, "")
        if reason:
            reason = reason[:120] + ("..." if len(reason) > 120 else "")
        print(f"  {name:<22} {marker:<8} {reason}")
    print(f"\nCompleted in {total_time:.1f}s")

    # --- Save results ---
    result_record = {
        "query": TEST_QUERY,
        "response": agent_text,
        "context": context[:500],
        "scores": scores,
        "reasons": reasons,
        "latency_s": round(elapsed, 2),
    }
    output_path = Path(__file__).parent / "results.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(result_record, ensure_ascii=False) + "\n")

    summary_path = Path(__file__).parent / "eval_output.txt"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("AUTOMATED EVALUATION SUMMARY — News Agent\n")
        f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total time: {total_time:.1f}s\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Query: {TEST_QUERY}\n")
        f.write(f"Response: {agent_text[:300]}{'...' if len(agent_text) > 300 else ''}\n\n")
        for name, score in scores.items():
            marker = f"{score}/5" if isinstance(score, (int, float)) else (score or "ERR")
            reason = reasons.get(name, "")
            if reason:
                reason = reason[:200] + ("..." if len(reason) > 200 else "")
            f.write(f"{name:<22} {marker:<8} {reason}\n")
        f.write("\n" + "=" * 60 + "\n")
    print(f"Results:  {output_path}")
    print(f"Summary:  {summary_path}")

    # --- Push to Foundry ---
    foundry_project = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if foundry_project:
        print("\nPushing evaluation results to Foundry...")
        evaluator_suite = create_evaluators()
        eval_config = {}
        column_mapping = {
            "query": "${data.query}",
            "response": "${data.response}",
            "context": "${data.context}",
        }
        for name, ev in evaluator_suite.items():
            cfg = EvaluatorConfig(column_mapping=column_mapping)
            eval_config[name] = cfg

        foundry_result = evaluate(
            evaluation_name="news-agent-eval",
            data=str(output_path),
            evaluators=evaluator_suite,
            evaluator_config=eval_config,
            azure_ai_project=foundry_project,
        )
        print("  Foundry evaluation run complete.")
        studio_url = foundry_result.get("studio_url", "")
        if studio_url:
            print(f"  View in Foundry: {studio_url}")
    else:
        print("\nNo FOUNDRY_PROJECT_ENDPOINT set — skipping Foundry upload.")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_evaluation())

# Copyright (c) Microsoft. All rights reserved.
"""
Automated Evaluation of a News Agent

Runs the Hacker News agent on a set of test queries, then evaluates every response
using the Azure AI Evaluation SDK (azure-ai-evaluation).  Evaluators span three categories:

  Quality:       Groundedness, Coherence, Fluency, Relevance
  Agent:         Intent Resolution, Tool Call Accuracy
  Risk & Safety: Content Safety (violence, self-harm, sexual, hate/unfairness)

All agent interactions and evaluation scores are instrumented with OpenTelemetry
and exported to Application Insights when APPLICATIONINSIGHTS_CONNECTION_STRING is set.
Evaluation scores are emitted as OTEL events attached to each query span, making
them visible in the App Insights transaction details view.

When FOUNDRY_PROJECT_ENDPOINT is set, results are also pushed to the Foundry
evaluation dashboard via the ``evaluate()`` batch API.

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
    "azure", "azure.core", "azure.identity", "azure.monitor",
    "azure.ai.evaluation", "opentelemetry", "urllib3",
]:
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

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
# Test dataset – each entry is a query the agent will answer, plus context
# that we know the tools will provide (used for groundedness scoring).
# ---------------------------------------------------------------------------

TEST_QUERIES = [
    {
        "query": "Give me a brief summary of the current top 3 Hacker News stories.",
        "description": "Basic top-stories summary",
    },
    {
        "query": "What are the newest stories on Hacker News right now? Show me 3.",
        "description": "Newest stories request",
    },
    {
        "query": "Which of the current best Hacker News stories are about programming?",
        "description": "Filtered best-stories query",
    },
]

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

    evaluators = {
        # Quality evaluators
        "groundedness": GroundednessEvaluator(model_config=model_config),
        "coherence": CoherenceEvaluator(model_config=model_config),
        "fluency": FluencyEvaluator(model_config=model_config),
        "relevance": RelevanceEvaluator(model_config=model_config),
        # Agent evaluators
        "intent_resolution": IntentResolutionEvaluator(model_config=model_config),
        "tool_call_accuracy": ToolCallAccuracyEvaluator(model_config=model_config),
    }

    # Risk & Safety evaluators require a Foundry project endpoint
    foundry_project = os.environ.get("FOUNDRY_PROJECT_ENDPOINT", "")
    if foundry_project:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
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
    else:
        print("No APPLICATIONINSIGHTS_CONNECTION_STRING — traces will be local only.")

    configure_otel_providers(
        exporters=exporters if exporters else None,
        enable_sensitive_data=True,
    )
    tracer = get_tracer()

    agent = create_news_agent()
    evaluators = create_evaluators()

    # --- Run all agent queries in parallel ---
    print(f"\nRunning {len(TEST_QUERIES)} agent queries in parallel...")
    overall_start = time.time()

    async def run_single_query(i, test_case):
        query = test_case["query"]
        desc = test_case["description"]

        # Step 1: Run agent inside a span
        start = time.time()
        session = agent.create_session()
        span = tracer.start_span(f"eval:query_{i}", kind=SpanKind.INTERNAL)
        span.set_attribute("eval.query", query)
        ctx = trace.set_span_in_context(span)
        token = otel_context.attach(ctx)
        response = await agent.run(query, session=session)
        otel_context.detach(token)
        agent_text = response.text
        elapsed = time.time() - start
        print(f"  [{i}/{len(TEST_QUERIES)}] {desc} — {elapsed:.1f}s")

        # Step 2: Extract context and tool calls from response
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

        # Step 3: Evaluate (all evaluators in parallel via thread pool)
        loop = asyncio.get_event_loop()

        def run_evaluator(name, evaluator):
            try:
                if name == "groundedness":
                    result = evaluator(query=query, response=agent_text, context=context)
                elif name == "tool_call_accuracy":
                    if not tool_calls:
                        return name, "N/A", "No tool calls in response"
                    result = evaluator(query=query, tool_calls=tool_calls, tool_definitions=TOOL_DEFINITIONS)
                elif name == "intent_resolution":
                    result = evaluator(query=query, response=agent_text, tool_definitions=TOOL_DEFINITIONS)
                elif name == "content_safety":
                    result = evaluator(query=query, response=agent_text)
                    sub = {}
                    for sub_key in ["violence", "self_harm", "sexual", "hate_unfairness"]:
                        sub[sub_key] = result.get(sub_key, "N/A")
                        sub[f"{sub_key}_reason"] = result.get(f"{sub_key}_reason", "")
                    cs_score = "pass" if result.get("content_safety_defect_rate", 0) == 0 else "fail"
                    cs_reason = f"defect_rate={result.get('content_safety_defect_rate', 'N/A')}"
                    return name, cs_score, cs_reason, sub
                else:
                    result = evaluator(query=query, response=agent_text)

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

        scores = {}
        for res in eval_results:
            name = res[0]
            if len(res) == 4:  # content_safety with sub-scores
                scores[name] = res[1]
                scores[f"{name}_reason"] = res[2]
                scores.update(res[3])
            else:
                scores[name] = res[1]
                scores[f"{name}_reason"] = res[2]

        # Step 4: Emit evaluation scores as OTEL span attributes & events
        for k, v in scores.items():
            if not k.endswith("_reason") and isinstance(v, (int, float)):
                span.set_attribute(f"eval.{k}", v)
        span.add_event("evaluation_scores", attributes={
            k: (str(v) if not isinstance(v, (int, float)) else v)
            for k, v in scores.items()
            if not k.endswith("_reason") and v is not None
        })
        span.end()

        return {
            "query": query,
            "description": desc,
            "response": agent_text,
            "context": context[:500],
            "scores": {k: v for k, v in scores.items() if not k.endswith("_reason")},
            "reasons": {k: v for k, v in scores.items() if k.endswith("_reason")},
            "latency_s": round(elapsed, 2),
        }

    results = await asyncio.gather(
        *[run_single_query(i, tc) for i, tc in enumerate(TEST_QUERIES, 1)]
    )
    results = list(results)
    total_time = time.time() - overall_start
    print(f"\nAll queries + evaluations completed in {total_time:.1f}s")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    # Filter to evaluators for the summary table (skip content_safety sub-scores)
    skip_in_summary = {"violence", "self_harm", "sexual", "hate_unfairness"}
    eval_names = [k for k in results[0]["scores"].keys() if k not in skip_in_summary]

    def fmt_score(val):
        if val is None:
            return f"{'ERR':>13}"
        if isinstance(val, str):
            return f"{val:>13}"
        return f"{val:>12.0f}/5"

    header = f"{'Query':<40} " + " ".join(f"{n:>18}" for n in eval_names)
    print(header)
    print("-" * len(header))

    for r in results:
        desc = r["description"][:39]
        vals = " ".join(fmt_score(r["scores"].get(n)) for n in eval_names)
        print(f"{desc:<40} {vals}")

    # Averages (numeric only)
    print("-" * len(header))
    avgs = []
    for n in eval_names:
        valid = [r["scores"][n] for r in results if isinstance(r["scores"].get(n), (int, float)) and r["scores"][n] is not None]
        if valid:
            avg = sum(valid) / len(valid)
            avgs.append(f"{avg:>17.1f}/5")
        else:
            avgs.append(f"{'N/A':>18}")
    print(f"{'Average':<40} {' '.join(avgs)}")

    # Save detailed results (JSONL)
    output_path = Path(__file__).parent / "results.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Save human-readable summary
    summary_path = Path(__file__).parent / "eval_output.txt"
    summary_lines = []
    summary_lines.append("=" * 60)
    summary_lines.append("AUTOMATED EVALUATION SUMMARY — News Agent")
    summary_lines.append(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    summary_lines.append(f"Total time: {total_time:.1f}s  |  Queries: {len(results)}")
    summary_lines.append(f"Evaluators: {', '.join(eval_names)}")
    summary_lines.append("=" * 60)
    summary_lines.append("")
    summary_lines.append(header)
    summary_lines.append("-" * len(header))
    for r in results:
        desc = r["description"][:39]
        vals = " ".join(fmt_score(r["scores"].get(n)) for n in eval_names)
        summary_lines.append(f"{desc:<40} {vals}")
    summary_lines.append("-" * len(header))
    summary_lines.append(f"{'Average':<40} {' '.join(avgs)}")
    summary_lines.append("")
    for r in results:
        summary_lines.append(f"--- {r['description']} ---")
        summary_lines.append(f"  Query:    {r['query']}")
        summary_lines.append(f"  Response: {r['response'][:200]}{'...' if len(r['response']) > 200 else ''}")
        summary_lines.append(f"  Latency:  {r['latency_s']}s")
        for k, v in r['scores'].items():
            reason = r['reasons'].get(f'{k}_reason', '')
            if reason:
                reason = reason[:120] + ('...' if len(reason) > 120 else '')
            summary_lines.append(f"  {k}: {v}  — {reason}")
        summary_lines.append("")
    summary_lines.append("=" * 60)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    print(f"Detailed results: {output_path}")
    print(f"Summary:          {summary_path}")

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

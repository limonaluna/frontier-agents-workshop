# Copyright (c) Microsoft. All rights reserved.
import sys
from pathlib import Path

# Add the project root to the path so we can import from samples.shared
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from samples.shared.model_client import create_chat_client
import logging
import os
import asyncio
import time
from typing import Annotated, List, Literal

import httpx
from agent_framework import Agent
from agent_framework.observability import get_tracer, configure_otel_providers
from agent_framework.openai import OpenAIChatClient
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter, AzureMonitorMetricExporter
from opentelemetry.trace import SpanKind
from pydantic import Field

from openai import AsyncOpenAI

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Log capture — collect all log records so we can write a summary later
# ---------------------------------------------------------------------------

class _LogCapture(logging.Handler):
    """Stores log records in memory for later markdown export."""
    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord):
        self.records.append(record)

_log_capture = _LogCapture()
_log_capture.setLevel(logging.DEBUG)
# Attach to root so we see everything
logging.getLogger().addHandler(_log_capture)
logging.getLogger().setLevel(logging.DEBUG)

"""
OpenAI Chat Client Direct Usage Example

Demonstrates direct OpenAIChatClient usage for chat interactions with OpenAI models.
Shows function calling capabilities with custom business logic.

"""

completion_model_name = os.environ.get("COMPLETION_DEPLOYMENT_NAME")
medium_model_name = os.environ.get("MEDIUM_DEPLOYMENT_MODEL_NAME")
small_model_name = os.environ.get("SMALL_DEPLOYMENT_MODEL_NAME")

completion_client=create_chat_client(completion_model_name)
medium_client=create_chat_client(medium_model_name)
small_client=create_chat_client(small_model_name)


def get_hackernews_story_ids(
    list_type: Annotated[
        Literal["top", "new", "best"],
        Field(description="Which Hacker News list to fetch: 'top', 'new', or 'best'."),
    ] = "top",
    limit: Annotated[
        int,
        Field(
            description="Maximum number of story IDs to return (1-50).",
            ge=1,
            le=50,
        ),
    ] = 10,
) -> List[int]:
    """Get a list of recent Hacker News story IDs using the Firebase API."""
    base = "https://hacker-news.firebaseio.com/v0"
    path_map = {
        "top": "topstories",
        "new": "newstories",
        "best": "beststories",
    }
    path = path_map[list_type]
    url = f"{base}/{path}.json"

    with httpx.Client(timeout=10) as client:
        response = client.get(url, params={"print": "pretty"})
        response.raise_for_status()
        ids = response.json() or []

    return ids[:limit]


def get_hackernews_story(
    story_id: Annotated[
        int,
        Field(description="The Hacker News story ID to retrieve."),
    ],
) -> dict:
    """Get the full JSON details of a Hacker News story by ID."""
    base = "https://hacker-news.firebaseio.com/v0"
    url = f"{base}/item/{story_id}.json"

    with httpx.Client(timeout=10) as client:
        response = client.get(url, params={"print": "pretty"})
        response.raise_for_status()
        data = response.json() or {}

    return data


# ---------------------------------------------------------------------------
# Markdown log summary — categorizes captured logs into observability sections
# ---------------------------------------------------------------------------

# Log categories with (label, logger-name-prefix-or-keyword matches)
_LOG_CATEGORIES = [
    ("OpenTelemetry / Tracing", ["opentelemetry", "otel"]),
    ("Azure Monitor Export", ["azure.monitor"]),
    ("Agent Framework", ["agent_framework"]),
    ("Azure Identity / Auth", ["azure.identity", "azure.core"]),
    ("HTTP Requests (httpx)", ["httpx"]),
    ("Azure AI / Evaluation", ["azure.ai"]),
]


def _categorize(record: logging.LogRecord) -> str:
    """Return a section heading for this log record."""
    name = record.name.lower()
    msg = record.getMessage().lower()
    for label, prefixes in _LOG_CATEGORIES:
        for pfx in prefixes:
            if name.startswith(pfx) or pfx in msg:
                return label
    return "Other"


def _write_log_summary(total_time: float):
    """Write an annotated markdown file with representative log extracts."""
    out = Path(__file__).parent / "observability_output.md"

    # Bucket records by category
    buckets: dict[str, list[logging.LogRecord]] = {}
    for r in _log_capture.records:
        cat = _categorize(r)
        buckets.setdefault(cat, []).append(r)

    # Section descriptions explaining *why* we see these logs
    section_notes = {
        "OpenTelemetry / Tracing": (
            "These logs come from the OpenTelemetry SDK — span creation, "
            "context propagation, and export.  They appear because we called "
            "`configure_otel_providers()` which sets up a TracerProvider with "
            "the Azure Monitor exporter."
        ),
        "Azure Monitor Export": (
            "The Azure Monitor exporter batches finished spans and metrics "
            "and sends them to Application Insights.  These logs show the "
            "export pipeline in action."
        ),
        "Agent Framework": (
            "The agent-framework library logs every LLM call, tool invocation, "
            "and message exchange.  With `enable_sensitive_data=True` the full "
            "message content is included, which is useful during development."
        ),
        "Azure Identity / Auth": (
            "When using RBAC (no API key), DefaultAzureCredential tries "
            "multiple credential sources.  These logs show which credential "
            "succeeded and token acquisition."
        ),
        "HTTP Requests (httpx)": (
            "The httpx library logs each outgoing HTTP request.  This covers "
            "both the Hacker News API calls (tool execution) and the Azure "
            "OpenAI chat completion requests."
        ),
        "Azure AI / Evaluation": (
            "Logs from the Azure AI Evaluation SDK — evaluator execution, "
            "prompt construction, and result processing."
        ),
        "Other": (
            "Miscellaneous logs that don't fall into the above categories."
        ),
    }

    # Preferred section order
    section_order = [label for label, _ in _LOG_CATEGORIES] + ["Other"]

    with open(out, "w", encoding="utf-8") as f:
        f.write("# Observability Log Summary\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"**Total runtime:** {total_time:.1f}s  \n\n")
        f.write(
            "This file contains representative log extracts from a single run "
            "of the observability news-agent sample.  Each section shows how "
            "the OpenTelemetry + Azure Monitor setup produces telemetry at "
            "different layers of the stack.\n\n"
        )

        for section in section_order:
            records = buckets.get(section)
            if not records:
                continue

            f.write("---\n\n")
            f.write(f"## {section}\n\n")
            note = section_notes.get(section, "")
            if note:
                f.write(f"_{note}_\n\n")

            f.write(f"**{len(records)} log entries captured** (showing up to 15 representative samples)\n\n")
            f.write("```\n")
            # Show first few and last few to give a representative sample
            shown = records[:10] + (records[-5:] if len(records) > 15 else records[10:15])
            seen = set()
            for rec in shown:
                line = f"[{rec.levelname:<7}] {rec.name}: {rec.getMessage()}"
                # Truncate very long lines
                if len(line) > 300:
                    line = line[:297] + "..."
                # Deduplicate identical lines
                if line in seen:
                    continue
                seen.add(line)
                f.write(line + "\n")
            if len(records) > 15:
                f.write(f"  ... ({len(records) - 15} more entries)\n")
            f.write("```\n\n")

        # Summary table
        f.write("---\n\n")
        f.write("## Summary\n\n")
        f.write("| Category | Log entries | Levels |\n")
        f.write("|---|---|---|\n")
        total = 0
        for section in section_order:
            records = buckets.get(section)
            if not records:
                continue
            levels = sorted(set(r.levelname for r in records))
            f.write(f"| {section} | {len(records)} | {', '.join(levels)} |\n")
            total += len(records)
        f.write(f"| **Total** | **{total}** | |\n")

    print(f"Log summary: {out}")


async def main() -> None:
    print("=== Hacker News Agent (with observability) ===\n")
    t0 = time.time()

    # Configure observability with Azure Monitor (Application Insights)
    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    exporters = []
    if connection_string:
        exporters.append(AzureMonitorTraceExporter(connection_string=connection_string))
        exporters.append(AzureMonitorMetricExporter(connection_string=connection_string))
        print("Application Insights exporters configured.")
    else:
        print("No APPLICATIONINSIGHTS_CONNECTION_STRING found — traces will be local only.")

    configure_otel_providers(
        exporters=exporters if exporters else None,
        enable_sensitive_data=True,
    )

    tracer = get_tracer()

    async def get_hn_ids_observed(
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
        with tracer.start_as_current_span(
            "tool:get_hackernews_story_ids", kind=SpanKind.CLIENT
        ) as span:
            span.set_attribute("tool.name", "get_hackernews_story_ids")
            return get_hackernews_story_ids(list_type=list_type, limit=limit)

    async def get_hn_story_observed(
        story_id: Annotated[
            int,
            Field(description="The Hacker News story ID to retrieve."),
        ],
    ) -> dict:
        """Get the full JSON details of a Hacker News story by ID."""
        with tracer.start_as_current_span(
            "tool:get_hackernews_story", kind=SpanKind.CLIENT
        ) as span:
            span.set_attribute("tool.name", "get_hackernews_story")
            return get_hackernews_story(story_id=story_id)

    agent = Agent(
        client=medium_client,
        instructions=(
            "You are a helpful news assistant that uses the provided tools "
            "to fetch and summarize Hacker News stories. When asked about "
            "Hacker News, first fetch relevant story IDs, then retrieve "
            "their details and provide concise summaries."
        ),
        tools=[get_hn_ids_observed, get_hn_story_observed],
    )

    session = agent.create_session()

    user_queries = [
        "Give me a brief summary of the current top 5 Hacker News stories.",
        "Now, focus on any stories related to AI or machine learning.",
        "Remind me which story had the highest score.",
    ]

    for query in user_queries:
        print(f"User: {query}")
        result = await agent.run(query, session=session)
        print(f"Agent: {result.text}\n")

    total_time = time.time() - t0
    print(f"Completed in {total_time:.1f}s")

    # --- Write observability log summary ---
    _write_log_summary(total_time)


if __name__ == "__main__":
    asyncio.run(main())
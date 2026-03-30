# Observability Demo Script

> A guided walkthrough for presenting the Agent Framework observability sample with Application Insights integration.

---

## Setting the stage

When you build agentic applications, the model doesn't just return text — it reasons, decides which tools to call, waits for results, and chains multiple steps together. That makes debugging and monitoring fundamentally harder than traditional API calls. You need answers to questions like:

- **What did the model actually decide to do?** Which tools did it call, with what arguments?
- **How long did each step take?** Was it the LLM call that was slow, or the external API?
- **What data flowed through the system?** What context did the model see, and what did it produce?
- **Did anything fail silently?** A tool might return garbage that the model politely works around.

OpenTelemetry (OTEL) solves this by providing a standard way to capture **traces** (distributed call trees), **spans** (individual operations), and **metrics** — and export them to any backend. The Agent Framework has built-in OTEL support, so you get auto-instrumentation of LLM calls and tool executions with a single line of setup.

In this demo we'll see that in action with a real agent.

---

## What the news agent does

The sample (`samples/observability/news-agent.py`) is a **Hacker News assistant** that:

1. **Fetches story IDs** from the Hacker News Firebase API (top, new, or best stories)
2. **Retrieves full story details** (title, author, score, URL) for each ID
3. **Summarizes the stories** in natural language using an Azure OpenAI model

The agent has two tools registered — one for fetching IDs, one for fetching story details. The model decides on its own when to call them and how to combine the results.

We run **three queries in a multi-turn session**:
- *"Give me a brief summary of the current top 5 Hacker News stories."* — triggers both tools: fetch IDs → fetch 5 stories → summarize
- *"Now, focus on any stories related to AI or machine learning."* — the model filters from memory, no re-fetch needed
- *"Remind me which story had the highest score."* — pure recall from session context

This gives us a nice mix of tool-heavy turns and pure-reasoning turns to observe.

---

## Prerequisites

1. Azure OpenAI deployment with RBAC access (`az login`)
2. `.env` configured with `AZURE_OPENAI_ENDPOINT` and model deployment names
3. `APPLICATIONINSIGHTS_CONNECTION_STRING` in `.env` (from your App Insights resource → Properties)
4. Dependencies installed: `pip install -r requirements.txt`

---

## Part 1 — Walk through the code

Open `samples/observability/news-agent.py` and highlight these four sections:

### 1.1 Setting up observability (lines ~97–112)

```python
connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
exporters = []
if connection_string:
    exporters.append(AzureMonitorTraceExporter(connection_string=connection_string))
    exporters.append(AzureMonitorMetricExporter(connection_string=connection_string))

configure_otel_providers(
    exporters=exporters if exporters else None,
    enable_sensitive_data=True,
)
```

**Talking points:**
- `configure_otel_providers()` is the single entry point — it sets up the full OpenTelemetry pipeline (tracer provider, meter provider, exporters)
- We pass Azure Monitor exporters so traces and metrics flow to Application Insights automatically
- `enable_sensitive_data=True` makes the framework log full message content (system prompts, user messages, tool arguments, tool responses) — great for debugging, disable in production

### 1.2 Custom tool spans (lines ~116–135)

```python
tracer = get_tracer()

async def get_hn_ids_observed(...) -> List[int]:
    with tracer.start_as_current_span(
        "tool:get_hackernews_story_ids", kind=SpanKind.CLIENT
    ) as span:
        span.set_attribute("tool.name", "get_hackernews_story_ids")
        return get_hackernews_story_ids(list_type=list_type, limit=limit)
```

**Talking points:**
- `get_tracer()` returns an OpenTelemetry tracer scoped to the agent framework
- We wrap each tool in a span — this captures execution time, success/failure, and custom attributes
- The `tool:` prefix in the span name makes these easy to query separately in App Insights
- `SpanKind.CLIENT` marks this as an outgoing call (to the Hacker News API)

### 1.3 Agent setup (lines ~138–150)

```python
agent = Agent(
    client=medium_client,
    instructions="You are a helpful news assistant...",
    tools=[get_hn_ids_observed, get_hn_story_observed],
)
```

**Talking points:**
- Standard agent setup — observability is orthogonal to agent configuration
- The framework auto-instruments all LLM calls (chat completions) — no extra code needed
- Tool calls made by the agent are also auto-instrumented with function name, duration, and success status

### 1.4 Multi-turn session (lines ~152–163)

```python
session = agent.create_session()

for query in user_queries:
    result = await agent.run(query, session=session)
```

**Talking points:**
- Three queries share a `session` — the agent remembers previous context
- Each `agent.run()` creates a parent span; LLM calls and tool calls are child spans
- This gives us a full distributed trace per turn, linked by `operation_Id`

---

## Part 2 — Run the agent

```bash
python samples/observability/news-agent.py
```

While it runs, narrate what you see in the console output:

| What you see | What to say |
|---|---|
| `Application Insights exporters configured.` | "Connection string was found — traces will flow to App Insights." |
| `Request URL: '…applicationinsights.azure.com//v2.1/track'` | "Here we see a batch of traces being sent to the ingestion endpoint." |
| `Response status: 200` | "200 — the traces were accepted." |
| `{'role': 'system', 'parts': [...]}` | "Because we enabled sensitive data, we can see the full system prompt." |
| `{'role': 'assistant', 'parts': [{'type': 'tool_call', ...}]}` | "The model decided to call a tool — you can see the function name and arguments." |
| `Function get_hn_ids_observed succeeded.` | "This is the auto-instrumentation — the framework tracks every tool call." |
| `Function duration: 0.85s` | "And the execution time, automatically." |
| `{'role': 'tool', 'parts': [{'type': 'tool_call_response', ...}]}` | "The tool result is logged too — you can inspect exactly what data came back." |
| `DefaultAzureCredential acquired a token from AzureCliCredential` | "We're using RBAC — no API keys anywhere in the code." |

After the three queries complete, point out that query 3 ("highest score") reuses session context without re-fetching data.

---

## Part 3 — Explore traces in Application Insights

> Allow 2–5 minutes after the run for traces to appear.

Open the Azure Portal → your Application Insights resource → **Logs**.

### 3.1 All agent traces

```kusto
dependencies
| where timestamp > ago(1h)
| where cloud_RoleName == "agent-framework" or name startswith "tool:"
| project timestamp, name, duration, success, data
| order by timestamp asc
```

**What to show:** The full list of spans — LLM calls and tool calls interleaved chronologically.

### 3.2 LLM call latencies

```kusto
dependencies
| where timestamp > ago(1h)
| where name contains "chat" or name contains "completions"
| project timestamp, name, duration, target, resultCode
| order by timestamp desc
```

**What to show:** How long each chat completion call took. Point out that parallel tool calls (5 story fetches) happen in a single LLM turn.

### 3.3 Custom tool spans

```kusto
dependencies
| where timestamp > ago(1h)
| where name startswith "tool:"
| project timestamp, name, duration, customDimensions["tool.name"]
| order by timestamp asc
```

**What to show:** Only custom tool spans. Highlight the `tool.name` attribute we set in the code.

### 3.4 End-to-end operation view

```kusto
dependencies
| where timestamp > ago(1h)
| project operation_Id, timestamp, name, duration
| order by operation_Id, timestamp asc
```

**What to show:** Group by `operation_Id` to see how LLM calls and tool spans relate within a single agent turn. Each turn has one parent span with child spans for each tool invocation.

### 3.5 Span attributes (sensitive data)

```kusto
dependencies
| where timestamp > ago(1h)
| extend prompt = tostring(customDimensions["gen_ai.prompt"])
| extend completion = tostring(customDimensions["gen_ai.completion"])
| where isnotempty(prompt) or isnotempty(completion)
| project timestamp, name, prompt, completion
| order by timestamp asc
```

**What to show:** Full prompt and completion content stored as span attributes. Emphasize that this is opt-in via `enable_sensitive_data=True` and should be disabled in production.

> **Note:** The detailed `{'role': 'system', ...}` message logs visible in the console are Python `logging` output. To also send those to App Insights, add an `AzureMonitorLogExporter` to the exporters list.

---

## Wrap-up — Key points to land

1. **Zero-plumbing instrumentation** — `configure_otel_providers()` + Azure Monitor exporters is all you need
2. **Auto + custom** — the framework auto-instruments LLM calls; you add custom spans for your own tools
3. **Full trace context** — multi-turn sessions, parallel tool calls, and LLM reasoning are all linked by `operation_Id`
4. **Sensitive data control** — full message logging is opt-in and queryable in App Insights
5. **Standard OTEL** — everything is OpenTelemetry-native; swap exporters for Jaeger, Zipkin, or any OTEL-compatible backend

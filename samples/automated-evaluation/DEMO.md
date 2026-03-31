# Automated Evaluation Demo Script

> A guided walkthrough for presenting automated quality, agent, and safety evaluation of an AI agent using the Azure AI Evaluation SDK — with observability and Foundry integration.

---

## Setting the stage

Building an AI agent is one thing — knowing whether it's *good* is another. When your agent summarizes Hacker News stories, how do you know the summaries are:

- **Grounded** in the actual data the tools returned (not hallucinated)?
- **Coherent** and logically structured?
- **Fluent** with natural, readable language?
- **Relevant** to what the user actually asked?
- **Safe** — free of violent, sexual, hateful, or self-harm content?
- **Using tools correctly** — calling the right functions with the right arguments?

You could review outputs manually, but that doesn't scale. What you need is **automated evaluation** — run your agent, then have a judge model score the response across multiple quality dimensions.

The Azure AI Evaluation SDK (`azure-ai-evaluation`) provides production-ready evaluators for exactly this. In this demo, we'll see how to wire them up to evaluate a real agent end-to-end, push results to Foundry, and track evaluation scores in Application Insights.

---

## What the program does

The sample (`samples/automated-evaluation/evaluate-news-agent.py`) does four things:

1. **Runs the news agent** on a test query ("summarize the top 3 HN stories")
2. **Evaluates the response** using 7 evaluators across three categories — all evaluators run in parallel
3. **Emits evaluation scores as OTEL events** to Application Insights for monitoring
4. **Pushes results to Foundry** for a visual evaluation dashboard

### Evaluator categories

| Category | Evaluators | What they measure |
|---|---|---|
| **Quality** | Groundedness, Coherence, Fluency, Relevance | Is the response accurate, well-structured, readable, and on-topic? |
| **Agent** | Intent Resolution, Tool Call Accuracy | Did the agent understand the user's intent and call the right tools? |
| **Safety** | Content Safety (violence, self-harm, sexual, hate/unfairness) | Is the response free of harmful content? |

### Architecture

- **Agent model** (`gpt-4.1-mini`) — generates the actual responses
- **Judge model** (`gpt-4.1-mini`) — scores the responses for quality and agent evaluators
- **Safety evaluator** — runs via the Foundry project endpoint (no local model needed)

---

## Prerequisites

1. Azure OpenAI with `gpt-4.1-mini` deployment
2. `.env` configured with:
   - `AZURE_OPENAI_ENDPOINT` and deployment names
   - `APPLICATIONINSIGHTS_CONNECTION_STRING` (for traces)
   - `FOUNDRY_PROJECT_ENDPOINT` (for safety evaluator + Foundry upload)
3. Dependencies installed: `pip install -r requirements.txt`

---

## Part 1 — Walk through the code

Open `samples/automated-evaluation/evaluate-news-agent.py` and highlight these sections:

### 1.1 Three categories of evaluators

```python
evaluators = {
    # Quality evaluators (1-5 score)
    "groundedness": GroundednessEvaluator(model_config=model_config, credential=credential),
    "coherence":    CoherenceEvaluator(model_config=model_config, credential=credential),
    "fluency":      FluencyEvaluator(model_config=model_config, credential=credential),
    "relevance":    RelevanceEvaluator(model_config=model_config, credential=credential),
    # Agent evaluators (1-5 score)
    "intent_resolution":  IntentResolutionEvaluator(model_config=model_config, credential=credential),
    "tool_call_accuracy": ToolCallAccuracyEvaluator(model_config=model_config, credential=credential),
}
# + ContentSafetyEvaluator when FOUNDRY_PROJECT_ENDPOINT is set
```

**Talking points:**
- Quality evaluators use a judge model to score responses on a 1-5 scale
- Agent evaluators assess whether the agent understood the intent and used tools correctly
- Content safety runs server-side via Foundry — no local model needed
- All evaluators share a single credential to avoid redundant auth calls
- All evaluators return a score plus a natural language reason explaining *why*

### 1.2 Parallel evaluator execution

```python
with ThreadPoolExecutor(max_workers=len(evaluators)) as executor:
    futures = {name: loop.run_in_executor(executor, run_evaluator, name, ev)
               for name, ev in evaluators.items()}
    eval_results = await asyncio.gather(*futures.values())
```

**Talking points:**
- All 7 evaluators run in parallel via a thread pool — not one after another
- This cuts evaluation time dramatically

### 1.3 OTEL evaluation events

```python
span.set_attribute(f"eval.{k}", v)
span.add_event("evaluation_scores", attributes={...})
```

**Talking points:**
- Evaluation scores are emitted as OTEL span attributes and events
- They appear in Application Insights alongside the agent trace
- You can query them with KQL to build monitoring dashboards

### 1.4 Foundry upload

```python
foundry_result = evaluate(
    evaluation_name="news-agent-eval",
    data=str(output_path),
    evaluators=evaluator_suite,
    azure_ai_project=foundry_project,
)
```

**Talking points:**
- The `evaluate()` batch API re-runs evaluators and uploads results to Foundry
- You get a visual dashboard with per-query scores, reasons, and trend tracking
- The link is printed at the end — open it in the browser to show the Foundry UI

---

## Part 2 — Run the evaluation

```bash
python samples/automated-evaluation/evaluate-news-agent.py
```

While it runs, narrate what you see:

| What you see | What to say |
|---|---|
| `Query: Give me a brief summary...` | "We send a single test query to the agent." |
| `Agent responded in 12.1s (786 chars)` | "The agent fetched story data and generated a summary." |
| `Evaluating...` | "Now all 7 evaluators run in parallel to score the response." |
| The score list | "Each evaluator returns a 1-5 score (or pass/fail for safety) with a reason." |
| `Pushing evaluation results to Foundry...` | "Now we upload to Foundry for a persistent dashboard." |
| `View in Foundry: https://ai.azure.com/...` | "Open this link to see the visual evaluation dashboard." |

### What the scores mean

| Evaluator | Score 5 | Score 1 |
|---|---|---|
| **Groundedness** | Every claim is supported by tool output | Hallucinated facts |
| **Coherence** | Logically consistent, well-structured | Contradictory or disorganized |
| **Fluency** | Natural, polished language | Awkward, hard to read |
| **Relevance** | Directly answers the question | Off-topic or misses the point |
| **Intent Resolution** | Fully understood and addressed the user's intent | Misinterpreted the request |
| **Tool Call Accuracy** | Called the right tools with correct arguments | Wrong tools or bad arguments |
| **Content Safety** | Pass = no harmful content detected | Fail = harmful content found |

---

## Part 3 — Inspect results

### Local output files

In `samples/automated-evaluation/`:
- **`results.jsonl`** — detailed JSON with scores, reasons, response text, and context
- **`eval_output.txt`** — human-readable summary

The reasons are especially useful for debugging low scores — they explain exactly what went wrong.

### Foundry dashboard

Open the Foundry link printed at the end. The dashboard shows:
- Per-evaluator score distributions
- Drill-down with reasons
- Trend tracking across evaluation runs

---

## Part 4 — Examine evaluation traces in Application Insights

### Access the Agents view

1. Go to your Application Insights resource in the Azure portal
2. Select **Agents (Preview)** in the navigation menu
3. You'll see the agent's traces including LLM calls, tool executions, and evaluation events

### KQL queries for evaluation scores

Open **Logs** in Application Insights and run these queries:

#### Query 1 — Evaluation scores

```kql
traces
| where message has "evaluation_scores"
| extend evalScores = parse_json(customDimensions)
| project
    timestamp,
    query = tostring(evalScores["eval.query"]),
    groundedness = todouble(evalScores["eval.groundedness"]),
    coherence = todouble(evalScores["eval.coherence"]),
    fluency = todouble(evalScores["eval.fluency"]),
    relevance = todouble(evalScores["eval.relevance"]),
    intent_resolution = todouble(evalScores["eval.intent_resolution"]),
    tool_call_accuracy = todouble(evalScores["eval.tool_call_accuracy"])
| order by timestamp desc
```

#### Query 2 — Average scores over time

```kql
dependencies
| where name startswith "eval:query"
| extend
    groundedness = todouble(customDimensions["eval.groundedness"]),
    coherence = todouble(customDimensions["eval.coherence"]),
    fluency = todouble(customDimensions["eval.fluency"]),
    relevance = todouble(customDimensions["eval.relevance"]),
    intent_resolution = todouble(customDimensions["eval.intent_resolution"]),
    tool_call_accuracy = todouble(customDimensions["eval.tool_call_accuracy"])
| summarize
    avg_groundedness = avg(groundedness),
    avg_coherence = avg(coherence),
    avg_fluency = avg(fluency),
    avg_relevance = avg(relevance),
    avg_intent = avg(intent_resolution),
    avg_tool_accuracy = avg(tool_call_accuracy)
    by bin(timestamp, 1h)
| order by timestamp desc
```

#### Query 3 — Agent tool calls and latency

```kql
dependencies
| where type == "gen_ai.tool"
| project timestamp, name, duration, success
| summarize
    call_count = count(),
    avg_duration_ms = avg(duration),
    failure_rate = countif(success == false) * 100.0 / count()
    by name, bin(timestamp, 1h)
| order by timestamp desc
```

---

## Wrap-up — Key points to land

1. **Three evaluation categories** — quality (groundedness, coherence, fluency, relevance), agent (intent resolution, tool call accuracy), and safety (content safety)
2. **Parallel evaluation** — all 7 evaluators run concurrently for fast feedback
3. **Context from tools** — tool outputs are the natural source of truth for groundedness evaluation
4. **OTEL integration** — evaluation scores flow into Application Insights as span attributes and events, queryable with KQL
5. **Foundry dashboard** — `evaluate()` pushes results to Foundry for visual tracking and trend analysis
6. **Actionable feedback** — every score comes with a reason explaining *why*, so you know exactly what to fix

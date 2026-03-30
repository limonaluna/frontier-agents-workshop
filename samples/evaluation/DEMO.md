# Self-Evaluation Demo Script

> A guided walkthrough for presenting the agent self-evaluation sample using groundedness scoring and self-reflection.

---

## The Idea

LLMs can hallucinate — they generate plausible-sounding content that isn't grounded in the provided context. This sample implements **Reflexion** (Shinn et al., NeurIPS 2023), a technique where an agent iteratively improves its own responses using verbal reinforcement.

The loop works like this:

1. Give the agent a question + context document
2. The agent generates a response
3. A **judge model** scores the response for **groundedness** (1–5 scale)
4. If the score isn't perfect, feed the score and reasoning back to the agent
5. The agent reflects and produces an improved response
6. Repeat until score = 5 or max iterations reached

This is a form of **self-evaluation** — the system uses an LLM to evaluate another LLM's output, then closes the feedback loop automatically.

---

## Prerequisites

1. Azure OpenAI with two deployments:
   - **Agent model** (`gpt-4.1-mini`) — generates the responses
   - **Judge model** (`gpt-4.1-nano`) — evaluates groundedness
2. `.env` configured with `AZURE_OPENAI_ENDPOINT` and deployment names
3. Dependencies installed: `pip install -r requirements.txt`

---

## Part 1 — Walk through the code

Open `samples/evaluation/self-evaluation.py` and highlight these sections:

### 1.1 Two-model architecture (lines ~52–54)

```python
DEFAULT_AGENT_MODEL = os.environ.get("COMPLETION_DEPLOYMENT_NAME")   # gpt-4.1-mini
DEFAULT_JUDGE_MODEL = os.environ.get("SMALL_DEPLOYMENT_MODEL_NAME")  # gpt-4.1-nano
```

**Talking points:**
- We use two separate models — a capable model generates responses, a cheaper/faster model judges them
- The judge model only needs to score groundedness, not generate creative content, so a smaller model works well
- This keeps evaluation cost low while maintaining quality

### 1.2 The groundedness evaluator (lines ~57–73)

```python
from azure.ai.evaluation import GroundednessEvaluator, AzureOpenAIModelConfiguration

evaluator = GroundednessEvaluator(model_config=judge_model_config)
```

**Talking points:**
- We use the Azure AI Evaluation SDK's built-in `GroundednessEvaluator`
- It scores how well a response is grounded in the provided context (1–5 scale)
- It also returns a `groundedness_reason` — a natural language explanation of why the score was given

### 1.3 The self-reflection loop (lines ~115–170)

```python
for i in range(max_self_reflections):
    raw_response = await agent.run(messages)
    agent_response = raw_response.text

    groundedness_res = evaluator(query=..., response=agent_response, context=context)
    score = int(groundedness_res['groundedness'])
    feedback = groundedness_res['groundedness_reason']

    if score == max_score:
        break  # Perfect — stop early

    # Feed the evaluation back to the agent
    reflection_prompt = (
        f"The groundedness score is {score}/5. "
        f"Explanation: [{feedback}]. "
        f"Reflect and improve your response..."
    )
    messages.append(Message("user", text=reflection_prompt))
```

**Talking points:**
- This is the core Reflexion pattern — generate, evaluate, reflect, retry
- The agent sees its previous response AND the evaluator's feedback in the conversation history
- The reflection prompt asks the agent to improve while sounding like a first response (no "based on feedback..." artifacts)
- We track the best score across iterations — sometimes a later attempt is worse, so we keep the best one
- Early termination on perfect score saves tokens and time

### 1.4 The input data (resources/suboptimal_groundedness_prompts.jsonl)

**Talking points:**
- 31 prompts across 5 domains: Legal, Medical, Technology, Financial, Retail
- Each prompt has a `context_document` (the grounding source), a `user_request`, and a combined `full_prompt`
- Task types include Fact Finding, Find & Summarize, Explanation/Definition, Pros & Cons
- These are specifically chosen to be prompts where naive LLM responses tend to hallucinate or go beyond the provided context

### 1.5 Batch processing and summary (lines ~190–360)

**Talking points:**
- The script processes prompts one by one and saves structured results to JSONL
- The summary shows average scores, improvement rates, and iteration statistics
- You can limit the run with `-n 3` to process just a few prompts for a quick demo

---

## Part 2 — Run the demo

### Quick run (1 prompt)

```bash
python samples/evaluation/self-evaluation.py -n 1
```

### Longer run (3 prompts, to see variation)

```bash
python samples/evaluation/self-evaluation.py -n 3
```

While it runs, narrate what you see:

| What you see | What to say |
|---|---|
| `Self-reflection iteration 1/3...` | "The agent generates its first response to the prompt." |
| `Groundedness score: 3/5` | "The judge model scored it 3 out of 5 — there's room for improvement." |
| `→ No improvement` or `✓ Score improved from 3 to 5` | "The agent reflected on the feedback and tried again — here we see whether it improved." |
| `✓ Perfect groundedness score achieved!` | "Perfect score — the loop breaks early, saving tokens." |
| `✓ Completed with score: 5/5 (best at iteration 2/3)` | "It took 2 iterations to reach a perfect score on this prompt." |

### After the run completes

Point out the summary statistics:

| Metric | What it tells us |
|---|---|
| Average best score | Overall quality across all prompts |
| Perfect scores (5/5) | What percentage achieved maximum groundedness |
| Average first score vs. final score | How much the self-reflection improved things |
| Responses that improved | Not every prompt needs reflection — some are perfect on the first try |
| Best on first try | Shows how often the agent gets it right without any feedback |

---

## Part 3 — Inspect the results

Open `samples/evaluation/resources/results.jsonl` to show the saved output. Each entry contains:

- **iteration_scores** — the score at each attempt (e.g., `[3, 4, 5]` shows progressive improvement)
- **best_response** — the highest-scoring response text
- **messages** — the full conversation history including reflection prompts
- **total_end_to_end_time** — wall clock time per prompt

---

## Wrap-up — Key points to land

1. **Self-evaluation closes the loop** — instead of just generating, the agent evaluates and improves its own output
2. **Two-model pattern** — use a capable model for generation, a cheaper one for evaluation
3. **Groundedness is measurable** — the Azure AI Evaluation SDK provides built-in evaluators with scores and explanations
4. **Reflexion works** — verbal feedback in the conversation history lets the agent correct hallucinations
5. **Production-ready pattern** — the same loop can be used with any evaluator (coherence, relevance, safety) and any number of iterations

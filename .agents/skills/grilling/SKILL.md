---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
metadata:
  version: 1.0.0
  base: mattpocock/skills/productivity/grilling@v1.3.1
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

## Style

Use plain language and optimize the prose for fast comprehension. Avoid semantic repetition and telegraphic prose. Use complete sentences by default; use headings, lists, or tables when they improve clarity, and never force complex material into one paragraph.

## Procedure

Work the tree in **rounds**.

1. Compute the **frontier**: every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.
2. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.
3. Apply the answers: each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round.

## Find the facts yourself

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

## Build each ballot

Word each question so "yes" accepts your recommended answer.

Ask each round through the `question` tool when it is exposed; direct markdown output is fallback only — never plain prose, never both ballots:

- Use a reader-comfortable CommonMark markdown formatting in all `question` tool fields exposed to the user: never fold long prose into a single paragraph.
- One round = the whole frontier in `questions[]`; wait for its result before recomputing the frontier. If the frontier exceeds 4 questions, split the same round into sequential `question` calls of ≤4 in frontier order, waiting for each result.
- Map one frontier decision to one entry:
  - `header` = 1–5 word title (≤30 chars).
  - `question` = `Qn: <decision> — <context and trade-offs>`.
  - `options[]` = 2–4 concrete choices with `description` stating the consequence.
  - Put your recommendation first and suffix its `label` with ` (Recommended)`.
  - Set `multiple: true` only for non-exclusive choices.
  - Never add Other/catch-all options (custom input is automatic).
- In chat text render only `Round N` plus one `➡️ <recommended choice + 1-sentence why>` per question for the trace — do not duplicate the full ballot in markdown when the tool is used.

## Fallback

Fallback, only when no `question` tool is exposed: render the round in markdown and wait for the reply in chat:

```markdown
Round 1/3 (est.)

❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

## Finish

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

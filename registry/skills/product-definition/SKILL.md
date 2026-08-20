---
skill_id: product-definition
name: Product Definition
description: Turn a goal into concrete requirements, scope boundaries, and open questions before any design or code work starts.
required_tools: [Read, Grep, Glob]
risk_level: low
phase: planning
---

# Product Definition

Use this skill at the start of any task whose output is "what should we
build," not "how do we build it."

## Do

- State who this is for and what problem it solves in one paragraph. If you
  can't, that's the finding — say so instead of inventing a persona.
- Write "done" as a testable statement, not a feeling. "Users can export a
  CSV of the last 90 days" is testable; "good UX" is not.
- List what's explicitly **out of scope**. An unscoped feature grows to fill
  whatever time exists.
- Surface every open question the Architect or Security agent needs
  answered, and name who owns answering it. An open question you silently
  resolved yourself is a decision nobody reviewed.

## Don't

- Don't pick a technology, a data model, or an architecture — that's the
  Architect agent's job downstream. Naming "how" here removes their reason
  to think about it.
- Don't write acceptance criteria you can't imagine a test for.

## Output shape

```
## Requirements
- ...

## Explicitly out of scope
- ...

## Open questions
- <question> — owner: <architect-agent | security-agent | human>
```

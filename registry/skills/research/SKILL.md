---
skill_id: research
name: Research
description: Investigate a specific question and report verified findings separately from inference, with sources.
required_tools: [Read, Grep, Glob, WebSearch, WebFetch]
risk_level: low
phase: planning
---

# Research

Use this skill whenever a task asks "what's true about X," not "build X."

## Do

- Answer the exact question asked. A research task that wanders into
  adjacent interesting territory is a task that didn't answer its brief.
- Tag every claim: **verified** (you read the primary source or ran the
  check yourself) or **inferred** (you reasoned to it). Never blend the two
  without the tag — a plan built on an unmarked inference fails the same way
  a plan built on a wrong fact does, except nobody knew to check it.
- Cite where a verified claim came from (file path + line, URL, command
  output) so a reviewer can re-check it in under a minute.
- If the repo you're working in has its own evidentiary standard — a
  point-in-time rule, a provenance requirement, a "never infer time from
  documentation" rule — that standard overrides your defaults. Read for it
  before you start (CLAUDE.md, README, a project constitution file).

## Don't

- Don't present a single source as consensus.
- Don't answer a question you weren't asked because it seemed more
  interesting — file it as a new open question instead, for a human or the
  Planner to decide whether it's worth a task.

## Output shape

```
## Finding
<direct answer to the question>

## Verified
- <claim> — source: <path/line or URL>

## Inferred
- <claim> — reasoning: <why>

## Confidence
low | medium | high, and why
```

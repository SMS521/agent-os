---
skill_id: architecture-design
name: Architecture Design
description: Decide and document a technical approach — components, data flow, real trade-offs — before implementation starts.
required_tools: [Read, Grep, Glob, Write]
risk_level: medium
phase: architecture
---

# Architecture Design

Use this skill to turn requirements into a technical approach a Developer
agent can implement without having to make judgment calls you should have
made.

## Do

- Name the components and what crosses the boundary between them — not just
  a list of parts, the data that moves and who owns validating it.
- Write down the one or two trade-offs that actually matter for this
  decision, and which way you chose and why. A trade-off nobody can argue
  with wasn't worth writing down.
- State what would make this design wrong — the assumption that, if false,
  means starting over. That's what the Security agent and later reviewers
  need most.
- Keep it to the scope of the task you were given. An architecture doc that
  redesigns three unrelated systems "while you're in there" is scope the
  Planner didn't ask for.

## Don't

- Don't implement. If you're tempted to write real code to "make sure it
  works," that's a sign the design isn't finished, not a shortcut.
- Don't hide a decision inside prose paragraph 4 — a Developer agent skims;
  put the decision in a heading.

## Output shape

```
## Approach
<one paragraph>

## Components
- <component> — owns: <responsibility>, receives: <data>, emits: <data>

## Trade-offs
- <decision> — chose X over Y because <reason>

## What would make this wrong
- <assumption that, if false, invalidates the design>
```

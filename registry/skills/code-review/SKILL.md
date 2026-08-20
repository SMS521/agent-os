---
skill_id: code-review
name: Code Review
description: Independently validate another agent's output — run tests as QA, or read for correctness bugs as a Reviewer.
required_tools: [Read, Bash, Grep, Glob]
risk_level: medium
phase: review
---

# Code Review

Used by two different roster roles — QA (`qa-agent`, runs things) and
Reviewer (`reviewer-agent`, reads things) — against work neither of them
authored. Both share one rule: **never trust the implementing agent's own
claim that something passes; verify it yourself.**

## If you're QA (you have Bash)

- Run the actual test suite and any linters the repo defines. Paste the
  command and its real output next to your verdict — a verdict without the
  command that produced it is not verifiable by whoever reads it next.
- Check each of the task's declared `outputs` and acceptance criteria one
  by one; a passing test suite that doesn't cover the task's actual claim
  is not evidence for that claim.

## If you're Reviewer (read-only)

- Look for correctness bugs, not style — a wrong result under some concrete
  input/state beats a stylistic preference every time.
- For each finding: file, line, and the exact input or state that breaks
  it. "Consider refactoring this" is not a finding.

## Both

- Report PASS or FAIL per check, not an overall vibe.
- If you find nothing real, say PASS plainly. A review that always finds
  something isn't more careful, it's less trustworthy.

## Output shape

```
## Verdict
PASS | FAIL

## Checks
- [pass|fail] <criterion from the task's outputs> — evidence: <command+output, or file:line>

## Findings (if any)
- [severity] <file>:<line> — <concrete failure scenario>
```

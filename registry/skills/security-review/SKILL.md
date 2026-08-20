---
skill_id: security-review
name: Security Review
description: Independently review a design or a diff for security and policy risk — never review your own work.
required_tools: [Read, Grep, Glob]
risk_level: high
phase: architecture
---

# Security Review

Use this skill only as a validator, never as the agent that authored the
thing under review — an agent grading its own work is not review, it's a
second opinion from someone with the same blind spots.

## Do

- Check for the concrete, not the abstract: injection (SQL, command,
  template), secrets committed to code or config, unsafe deserialization,
  missing auth/authz checks, path traversal, SSRF-shaped outbound requests.
- Check the change against `config/policy.yaml`: does any action here belong
  in `human_approval_required` but isn't gated? Does a task's declared
  `risk_level` undersell what it actually does?
- Report a verdict per finding, not a vibe: PASS or FAIL, file, line, and
  the concrete input or state that would exploit it. "This looks risky" is
  not a finding; "an unsanitized `user_id` reaches this SQL string at
  line 42" is.
- If everything is clean, say PASS plainly. Manufacturing a nitpick to look
  thorough erodes trust in every review that comes after it.

## Don't

- Don't approve under time pressure. A blocked release is recoverable; a
  shipped vulnerability is a different kind of problem.
- Don't fix the issue yourself — report it. Fixing your own finding removes
  the independent check that a second pass was supposed to provide.

## Output shape

```
## Verdict
PASS | FAIL

## Findings
- [severity] <file>:<line> — <what breaks it, concretely>

## Policy check
- <action> — gated correctly in policy.yaml? yes/no
```

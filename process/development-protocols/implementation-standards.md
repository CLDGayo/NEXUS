# Implementation Standards

## Core Principles

- Follow YAGNI, KISS, and DRY.
- Read `process/context/all-context.md` first, then load only the relevant context group or root file.
- Prefer updating existing files over creating parallel "enhanced" variants.
- Implement real code paths rather than mock-only stand-ins unless the user explicitly asks for a mock or stub.

## Code Organization

- Use descriptive kebab-case filenames.
- Keep TypeScript and JavaScript source files roughly under 200 lines when practical; split by responsibility when files become hard to reason about.
- Prefer focused modules, helpers, and composition over large mixed-purpose files.
- Markdown planning, context, agent, and skill files are exempt from the 200-line rule.

## Implementation Behavior

- Follow established architecture and local code patterns before inventing new ones.
- In utility or helper layers, prefer result objects over throwing when the local repo pattern expects recoverable errors.
- Handle edge cases and error paths deliberately.
- Prioritize readable, maintainable code over clever abstractions.

## Tooling

- Use `pnpm`, not `npm`.
- Use Context7 for library and API docs or setup guidance.
- Use `gh` for GitHub automation when needed.
- For database debugging, follow the current repo stack and context docs; do not assume Drizzle or SQLite unless the specific package actually uses them.

## Quality Gates

- Ensure code is syntactically valid and compiles where applicable.
- Run the most relevant tests for the change before calling work complete.
- Use code review or reviewer agents for meaningful implementation changes.
- Do not wave away failing tests just to force a green status.

## Risky Work Evidence Contract

For high-risk work, use a manual-first evidence pack before calling the change ready for finalize, push, or human handoff.

High-risk classes include:

- auth or identity flows
- billing, payments, or credit accounting
- schema/data migrations or destructive writes
- public API or external contract changes
- deploy/runtime/container/proxy/gateway behavior
- permission, secret, or trust-boundary logic

Preferred artifact set in the selected plan's reports `harness/` folder:

- `risk-gate.json`
- `context-snippets.json`
- `verification.json`
- `review-decision.json`
- `adversarial-validation.json` for high-risk or adversarial paths

Auto-stop rule:

- if risk is `high`, do not treat the work as ready to finalize until the evidence pack exists and the reviewer decision is recorded
- if the evidence pack is missing, say so explicitly instead of implying the work is proven

This contract is manual-first and opt-in by risk class. It is not a default blocking hook.

## Test Fixture Correctness

### Short-turn bypass footgun

The NEXUS guardrail pipeline (`rag/guardrails/pipeline.py`) includes a pre-existing short-turn
bypass: if `query ≤ 8 words AND answer ≤ 40 words`, `citation` and `exact_match` validators are
skipped with `reason="short-turn bypass"` regardless of surface.

This means a test fixture that uses a short query string and a short answer string will trigger
the bypass and never reach a surface-specific bypass branch (e.g., `outbound_recovery_bypass`).
The test will appear to pass while proving nothing about the real code path.

Rule: when testing a surface-specific guardrail bypass, use an answer that exceeds 40 words
to ensure the short-turn bypass does not fire first. Also assert on the `reason` string returned
by the validator — `"outbound_recovery_bypass"`, `"vision_bypass"`, etc. — not just `passed=True`.

General principle: before writing a bypass test, identify every *prior* bypass that could fire
for the fixture's input shape. Size the fixture to avoid those prior gates, so the test proves
the intended gate is the operative mechanism.

## Commit Hygiene

- Keep commits focused on the requested change.
- Never commit secrets or credentials.
- Use clean professional commit messages, ideally conventional-commit style when it fits the change.

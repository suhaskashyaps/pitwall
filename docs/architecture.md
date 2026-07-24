# Architecture

Pitwall makes a Fable 5 session an architect over cheaper external CLI agents ("lanes"), so premium tokens buy judgment and volume lands elsewhere.

## Premise

The session runs the most expensive model as the architect. Its tokens go to decomposition, specs, routing, and verdicts. Implementation volume goes to lanes: named model-harness combinations (a model paired with the CLI harness that drives it), driven headlessly under a shared contract. The economics only work if the architect's token volume stays low: emit judgment, keep context lean, reason once then hand off. Typing implementation code in the architect is a failure of the pattern.

## Three components

### Orchestration skill

Routing doctrine for the architect. You decompose work, write five-part specs, pick a tier (default, cross-vendor, race, suggest, advisor), and verify before accepting any report. You consult the advisor at commitment boundaries. You re-route on `unavailable` explicitly; you never absorb a substitution in silence. The skill does not implement.

### Lane-runner agent

Generic dispatcher. You pass it one `LANE: <id>` line plus a five-part spec. It resolves the lane from user config (`lanes.json`), preflights harness binary and required env sources, invokes the named harness headlessly, verifies independently, and returns a LANE REPORT. It never implements the task itself. Lane ids are never special-cased in its logic; all per-lane behavior comes from JSON fields (`harness`, `model`, `env`, `extra_flags`, `capabilities`, `timeout_seconds`).

### Fable-advisor agent

Read-only second opinion at commitment boundaries: architecture, migrations, API shapes, refactors, or a problem that has resisted two attempts. You pass the decision, constraints, and options. It returns a short verdict and the risk that decides it. It advises only; it never edits files.

## The five-part spec

Implementers share none of the architect's conversation context. Every delegation carries all five parts:

1. **Objective**: what to build or change, one paragraph
2. **Files**: exact paths to create or modify
3. **Interfaces**: signatures, types, or API shapes the code must match
4. **Constraints**: conventions and things not to touch
5. **Verification**: the command(s) that prove it works

A spec you cannot finish writing means the decision is not made yet. That is architect work, not a reason to hand ambiguity to a cheaper model.

## LANE REPORT

Every dispatch ends in a fixed report shape:

```
LANE REPORT (<lane-id>)
MODEL-HARNESS: <model or "harness default"> on the <harness> harness
STATUS: complete | partial | timeout | unavailable | suggested
OBJECTIVE: …
CHANGES: …
VERIFIED: …
HARNESS SAID: …
GAPS: …
```

Reports are claims, not evidence. Before accepting work, read the diff and re-run the verification command (or spot-check quoted output against the tree). "Should work" or a report with no command output means the task is not done. A lane that reports a spec gap gets a corrected spec, not "use your judgment."

## Failure discipline

When a lane cannot run (missing binary, missing env source, unknown id, cancelled harness turn), lane-runner returns `STATUS: unavailable` with the exact missing piece and stops. It never implements the task as a fallback. It never substitutes another lane. The orchestrator reports the unavailability to the user and re-routes the same spec to the next adequate lane by tier, or states a deliberate downgrade. Silent substitution defeats routing: the caller chose that lane's cost, vendor, and model on purpose.

## Key design decisions

**Lanes live in user config, not agent files.** Adding a model-harness is a JSON entry. Disabling a lane is deleting its entry. Fleet edits require no plugin change. The closed set is harnesses, not models.

**One generic lane-runner instead of one agent per lane.** Lane ids must never be special-cased in agent logic. Config fields drive harness, model, env shim, flags, capabilities, and timeout. The inventory can change without rewriting dispatcher prose.

**Harnesses run under `acceptEdits` (or equivalent workspace-write).** The harness can write files; it cannot run arbitrary shell. Lane-runner creates parent directories before dispatch and runs verification itself, so evidence is independently produced. Corollary for the grok harness: exit code 0 alone is not success. Success is gated on the JSON `stopReason`: anything but `EndTurn` (especially `Cancelled`) is failure, because a cancelled turn can exit 0 with empty output.

**The harness decides the wire protocol.** Claude speaks Anthropic Messages; codex speaks OpenAI Responses only; grok speaks xAI's protocol. A model-harness works only if the model's endpoint speaks that protocol. A local gateway that translates protocols is what unlocks third-party models on a given harness.

## What the plugin does not do

- No fallback implementation by the dispatcher when a lane is unavailable.
- No automatic lane failover without reporting: every substitution is an explicit orchestrator decision.
- No support for running the architect on a cheaper model. The session is Fable 5 by design; the premium is for judgment, not for typing volume.

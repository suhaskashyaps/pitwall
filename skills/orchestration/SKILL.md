---
name: orchestration
description: Routing doctrine for the Fable 5 architect-as-orchestrator pattern — how a session running Fable delegates implementation to a configurable fleet of cheaper lanes (grok, codex, claude harnesses, third-party models via env shims) to minimize cost. USE WHEN delegating implementation work, choosing a lane, writing a spec for a subagent, deciding whether to consult fable-advisor, managing session cost, or running any multi-task build where the session is the architect.
---

# Orchestration — the architect's routing doctrine

The session is the architect: it owns requirements, architecture, decomposition, specs, routing, and verification. It should almost never type implementation code. Every implementation task gets routed to the cheapest lane that is adequate for it — escalation is deliberate, per task, never a fixed binding. This doctrine assumes the session model is Fable 5 — the most expensive lane in the system. It does not support running the architect on a cheaper model.

## Cost discipline — the prime directive

The session model is the most expensive lane in the system, on both input and output tokens. The whole economic case for this pattern is keeping its token volume low: spend Fable on judgment, spend the cheap lanes on volume. Three rules follow.

**Emit judgment, not volume.** The architect's output is decomposition, specs, routing decisions, verdicts on diffs, and short reports. It does not type implementation code, test bodies, boilerplate, or config files. A code block longer than an interface signature or a few illustrative lines is a spec that hasn't been delegated yet — stop and delegate it. Fixing a lane's bug by hand is the same failure in disguise: send a corrected spec back to the cheap lane instead.

**Keep the context lean.** Everything in the architect's context is re-read at architect prices on every turn. Delegate broad exploration, codebase searches, and log-grepping to a cheap read-only agent and keep only the conclusions; read files yourself only when the decision genuinely depends on the exact code. Don't paste long files, full diffs, or verbose command output into the conversation when a path reference or an excerpt will do.

**Reason once, then hand off.** Do the hard thinking — the architecture, the interface design, the debugging hypothesis — in one pass, capture it in the spec, and let the cheap lane carry it from there. Re-deriving decisions across turns burns the premium twice.

What stays with the architect regardless of cost: decomposition, interface design, hypothesis selection when debugging, spec writing, lane routing, and judging verification evidence. Those tokens are what the premium is for — everything else is a candidate for delegation.

## The lanes

Each lane is a named model-harness: a model paired with the CLI harness that drives it. Every LANE REPORT calls out the model-harness combination it actually ran. Route against `~/.claude/pitwall/lanes.json` by capability tier:

| Tier | Route to | When |
|---|---|---|
| Default | the lane named by `default_lane` in `lanes.json` | Spec fully determines the outcome: boilerplate, wiring, CRUD, mechanical edits |
| Cross-vendor | any lane whose harness+model differs from the session's vendor | Correctness/completeness critical enough to want a second family |
| Race | two edit-capable lanes on the same spec | High-stakes — pick the stronger diff |
| Suggest | lanes with `capabilities: ["suggest-only"]` | Quick draft, oracle check, or all edit lanes unavailable |
| Advisor | `fable-advisor` agent | Not an implementation lane — see Commitment boundaries |

Read `lanes.json` at delegation time and route only to lanes present in it. Disabling a lane means deleting its entry. Adding a lane means adding a JSON entry; no plugin code change is required.

Deciding rule: how much does the outcome depend on judgment the spec can't capture? Little → use the Default tier; you will verify anyway. A lot, and mistakes are costly → use the Race tier on the same spec and pick the stronger diff, or keep that piece with the architect.

Choosing between vendor families is not a capability ranking — it is a failure-distribution question. Any lane from a different family gives the Fable architect genuine cross-vendor review; racing lanes from different vendor families buys a third independent perspective for one extra lane's cost.

## Lane health

When a lane returns `STATUS: unavailable`, report it to the user and re-route the same spec to the next adequate lane by tier. Never silently absorb a substitution. If every edit-capable lane is unavailable, say so plainly and either use a suggest-only lane for a draft or implement with a Claude subagent, explicitly stating the downgrade.

## The spec contract

Implementers share none of your conversation context. Every delegation prompt carries all five parts:

1. **Objective** — what to build or change, one paragraph
2. **Files** — exact paths to create or modify
3. **Interfaces** — signatures, types, or API shapes the code must match
4. **Constraints** — project conventions, things not to touch
5. **Verification** — the command(s) that prove it works

A spec you can't finish writing is a signal the decision isn't made yet — that's architect work, not a reason to hand the ambiguity to a cheaper model.

## Parallelism

Independent specs (no shared files, no ordering dependency) launch as parallel agents in a single message. Sequential chains and single-file surgery stay serial. For high-stakes work, a pick-the-stronger-diff race across edit-capable lanes on the same spec, architect judges, buys independent confidence for one extra lane's cost.

## Commitment boundaries

Consult `fable-advisor` (read-only, verdict in under 300 words) at the moments that decide whether the next hour is wasted:

- Before committing to an architecture, data migration, API shape, or refactor strategy
- Whenever the same problem has resisted two distinct attempts
- Once before declaring a multi-step deliverable done

Pass it the decision, the constraints, and the options considered. Act on the verdict or surface the disagreement — never silently ignore it. (If the session itself already runs on Fable, the advisor still earns its keep as a context-clean skeptic reading the actual code.)

## Verification

Reports are claims, not evidence. Before accepting any lane's work: read the diff, and re-run the verification command (or spot-check its quoted output against the working tree). "Should work", "tests should pass", or a report with no command output means the task is not done. A lane that reports a spec gap gets a corrected spec, not a "use your judgment".

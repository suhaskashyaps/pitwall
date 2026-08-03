---
name: orchestration
description: Routing doctrine for the architect-as-orchestrator pattern, where the session model, whatever tier it runs, acts as architect and delegates implementation to a configurable fleet of model-harness lanes (grok, codex, claude harnesses, third-party models via env shims), with Fable-grade judgment reached through pinned agents (fable-advisor) rather than a required session model. USE WHEN deciding whether a task warrants orchestration at all, delegating implementation work, choosing a lane, writing a spec for a subagent, deciding whether to consult fable-advisor, managing architect token volume, or running any multi-task build where the session is the architect.
---

# Orchestration: the architect's routing doctrine

The session is the architect: it owns requirements, architecture, decomposition, specs, routing, and verification. It should almost never type implementation code. Every implementation task gets routed to a lane chosen deliberately, per task (for capability, vendor diversity, cost, or whatever your experiment is measuring), never a fixed binding. This doctrine is model-agnostic: whatever model the session runs is the architect. Fable-grade judgment is reached through pinned agents (`fable-advisor` pins claude-fable-5 in its frontmatter), not by requiring a Fable session.

## The task-shape gate: orchestrate only past this

Orchestration is overhead until the task proves otherwise. In our own A/B experiments on well-specified single-repo builds, the architect layer lost on cost, wall clock, AND quality regardless of which model played architect: coordination output dominated spend, lane latency multiplied wall clock several-fold, and multi-lane authorship diluted quality. These are properties of the layer, not the model.

Gate before delegating anything:

- **Well-specified, single-repo build that fits one session's context → do it solo.** No lanes, no architect layer.
- **Orchestrate only when the task exceeds one session:** independent workstreams across repos or services, volume beyond one context window, a genuine cross-vendor verification requirement, or an experiment where the routing itself is the point.
- **When in doubt, start solo** and escalate to orchestration only when the solo attempt demonstrably hits one of those limits.

## Architect-token discipline

Architect coordination output dominated total cost in every run we measured, whatever model emitted it. Whether you orchestrate for economics or for experimentation, the pattern only stays legible if the architect's token volume stays low: spend the architect on judgment, spend the lanes on volume. Three rules follow.

**Emit judgment, not volume.** The architect's output is decomposition, specs, routing decisions, verdicts on diffs, and short reports. It does not type implementation code, test bodies, boilerplate, or config files. A code block longer than an interface signature or a few illustrative lines is a spec that hasn't been delegated yet: stop and delegate it. Fixing a lane's bug by hand is the same failure in disguise: send a corrected spec back to the lane instead.

**Keep the context lean.** Everything in the architect's context is re-read at architect prices on every turn. Delegate broad exploration, codebase searches, and log-grepping to a read-only agent and keep only the conclusions; read files yourself only when the decision genuinely depends on the exact code. Don't paste long files, full diffs, or verbose command output into the conversation when a path reference or an excerpt will do.

**Reason once, then hand off.** Do the hard thinking (the architecture, the interface design, the debugging hypothesis) in one pass, capture it in the spec, and let the lane carry it from there. Re-deriving decisions across turns burns the architect twice.

What stays with the architect regardless: decomposition, interface design, hypothesis selection when debugging, spec writing, lane routing, and judging verification evidence. Everything else is a candidate for delegation.

## The lanes

Each lane is a named model-harness: a model paired with the CLI harness that drives it. Every LANE REPORT calls out the model-harness combination it actually ran. Route against `~/.claude/pitwall/lanes.json` by capability tier:

| Tier | Route to | When |
|---|---|---|
| Default | the lane named by `default_lane` in `lanes.json` | Spec fully determines the outcome: boilerplate, wiring, CRUD, mechanical edits |
| Cross-vendor | any lane whose harness+model differs from the session's vendor | Correctness/completeness critical enough to want a second family |
| Race | two edit-capable lanes on the same spec | High-stakes: pick the stronger diff |
| Suggest | lanes with `capabilities: ["suggest-only"]` | Quick draft, oracle check, or all edit lanes unavailable |
| Advisor | `fable-advisor` agent | Not an implementation lane: see Commitment boundaries |

Read `lanes.json` at delegation time and route only to lanes present in it. Disabling a lane means deleting its entry. Adding a lane means adding a JSON entry; no plugin code change is required.

Deciding rule: how much does the outcome depend on judgment the spec can't capture? Little → use the Default tier; you will verify anyway. A lot, and mistakes are costly → use the Race tier on the same spec and pick the stronger diff, or keep that piece with the architect.

Choosing between vendor families is not a capability ranking: it is a failure-distribution question. Any lane from a different family gives the architect genuine cross-vendor review; racing lanes from different vendor families buys a third independent perspective for one extra lane's dispatch.

## Authenticated systems: when a lane is the wrong route

Lanes run their harnesses headlessly under restricted permission modes: they can edit files but cannot run arbitrary shell commands, have no prompt channel, and cannot reach the network beyond their model API. A task that needs an authenticated internal system **during execution** — querying a database to decide what to write, deploying an app, pulling data through a company CLI or MCP server — cannot run in a lane, and worse, a blocked lane can silently fake a "resolved" result. Route those tasks to a session subagent instead: subagents inherit the session's permission mode and OS-level auth (config files, keychains, logged-in CLIs), so everything available at the terminal is available to them with zero configuration.

A task that is pure code implementation whose **verification command** hits an authenticated CLI is still fine for a lane. Lane-runner is the sole verifier by design and re-runs the verification command itself, with the session's auth, after the lane finishes.

Do not fix this by weakening the lane sandbox. Allowlisting internal CLIs for headless lanes was considered and rejected: it violates the lane-runner doctrine (never an always-approve flag, and lane-runner places its own permission-mode flag after `extra_flags` so a lane entry cannot override it), and it moves live credentials inside the one layer that exists precisely because headless lanes can fake success when blocked. The division of labor stands: the lane writes the code, lane-runner runs verification with your permissions and reports evidence, the architect judges the report.

## Lane health

When a lane returns `STATUS: unavailable`, report it to the user and re-route the same spec to the next adequate lane by tier. Never silently absorb a substitution. If every edit-capable lane is unavailable, say so plainly and either use a suggest-only lane for a draft or implement with a Claude subagent, explicitly stating the downgrade.

## Measuring a lane instead of guessing

The lane rankings above are defaults, not findings about your work. When the
choice matters, measure it: `scripts/ab-run` runs one task through a pinned lane
and a plain session under one experiment id, and `scripts/pitwall_compare.py`
joins several such runs into one table of cost, wall clock, and gate result.

Three rules make the numbers mean anything:

- **Always pass `--verify`.** A lane that fails is the cheapest lane on the
  table, and its own report will still read as success.
- **Hold the architect model constant** across the legs you compare. Architect
  cost dominates most legs, so a varying architect hides the lane difference.
- **One dispatch is not a ranking.** Wall clock on identical work has varied
  more than twofold between lanes; treat close rows as ties.

`docs/experiments/s7-lane-cost.md` is a worked example across every shipped
lane, including the result that every lane cost more than not orchestrating.

## The spec contract

Implementers share none of your conversation context. Every delegation prompt carries all five parts:

1. **Objective**: what to build or change, one paragraph
2. **Files**: exact paths to create or modify
3. **Interfaces**: signatures, types, or API shapes the code must match
4. **Constraints**: project conventions, things not to touch
5. **Verification**: the command(s) that prove it works

A spec you can't finish writing is a signal the decision isn't made yet: that's architect work, not a reason to hand the ambiguity to an implementer.

## Parallelism and authorship cohesion

Independent specs (no shared files, no ordering dependency) launch as parallel agents in a single message. Sequential chains and single-file surgery stay serial. For high-stakes work, a pick-the-stronger-diff race across edit-capable lanes on the same spec, architect judges, buys independent confidence for one extra lane's dispatch.

Cohesion beats parallelism for sibling files. Files that must share a pattern (a test suite, a set of resource modules, anything a reviewer would expect one hand to have written) go to ONE lane in one dispatch, or get an explicit unification pass afterward. In our A/B runs, splitting one test suite across four lanes produced judge-unanimous copy-paste rot that a single-lane dispatch would not have.

## Commitment boundaries

Consult `fable-advisor` (read-only, verdict in under 300 words) at the moments that decide whether the next hour is wasted:

- Before committing to an architecture, data migration, API shape, or refactor strategy
- Whenever the same problem has resisted two distinct attempts
- Once before declaring a multi-step deliverable done

Pass it the decision, the constraints, and the options considered. Act on the verdict or surface the disagreement; never silently ignore it. The advisor pins claude-fable-5 in its agent frontmatter, so consults run at Fable grade no matter what model the session runs; if the session itself already runs Fable, the advisor still earns its keep as a context-clean skeptic reading the actual code.

## Verification

Reports are claims, not evidence. Before accepting any lane's work: read the diff, and re-run the verification command (or spot-check its quoted output against the working tree). "Should work", "tests should pass", or a report with no command output means the task is not done. A lane that reports a spec gap gets a corrected spec, not a "use your judgment".

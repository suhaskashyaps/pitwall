# Lane cost on one seeded task

Eleven model-harness lanes, each pinned to a single lane for the whole run, on a
byte-identical seed, against a baseline session that used no orchestration at all. This is the run behind the
[Findings](../../README.md#findings) section.

It is a case study, not a benchmark. One dispatch per lane, one machine, one day,
one task. Read it for method and for the shape of the result, and re-measure on
your own work before acting on it.

## What was measured

The seed is a build task with a deterministic acceptance gate: an in-memory
registry of 12 resources with referential integrity, a shared engine module, a
line cap forcing the resource modules to stay declarative, and one test file per
resource. `python3 gate.py` exits 0 and `python3 -m unittest discover` passes, or
the leg failed. Nothing about the task is a judgment call.

Every leg received the same task string, byte for byte. Each pitwall leg pinned
every implementation dispatch to one lane through `ab-run --lane`, with no
in-session implementation and no substitution if the lane was unavailable. The
architect was held constant at `claude-sonnet-5` across all eleven, so
lane-to-lane differences are not confounded by a varying architect.

The baseline is a plain Claude Code session on the same seed with no orchestration.

Costs come from each harness's own usage capture, priced through
`config/prices.json`. Wall clock comes from per-leg start and end markers, never
from harness-reported `duration_ms`, which proved unreliable in earlier runs.
Gates were re-run by the harness after each leg rather than taken from any
lane's self-report.

## Results

Prices as of 2026-07-26. All twelve legs passed both gates.

The baseline is one ordinary Claude Code session doing the task itself: no lanes,
no architect, so it has no lane or architect cost to split out. Every other row
delegated all implementation to the named model-harness, with `claude-sonnet-5`
as architect. Model names are the ones the harness actually reported in its usage
capture, not the ones the config requested.

| leg | model | harness | lane $ | architect $ | total $ | total/base | lane/base | wall clock | tests |
|---|---|---|---|---|---|---|---|---|---|
| no orchestration | claude-sonnet-5 | Claude Code | n/a | n/a | 1.129865 | 1.000x | n/a | 4m02s | 97 |
| `glm-codex` | glm-5.2 | Codex CLI | 0.478210 | 0.860098 | 1.338308 | 1.184x | 0.423x | 9m15s | 72 |
| `codex-gpt56` | gpt-5.6-sol | Codex CLI | 0.650406 | 0.775725 | 1.426131 | 1.262x | 0.576x | 5m10s | 72 |
| `grok45-codex` | grok-4.5 | Codex CLI | 0.471628 | 1.043434 | 1.515061 | 1.341x | 0.417x | 6m50s | 72 |
| `sonnet5-grok` | claude-sonnet-5 | Grok CLI | 0.665705 | 0.980427 | 1.646132 | 1.457x | 0.589x | 8m25s | 81 |
| `kimi-cc` | kimi-k3 | Claude Code CLI | 0.833693 | 0.878077 | 1.711770 | 1.515x | 0.738x | 9m01s | 73 |
| `glm-grok` | glm-5.2 | Grok CLI | 0.170299 | 1.874153 | 2.044452 | 1.809x | 0.151x | 22m41s | 97 |
| `grok` | grok-4.5-build | Grok CLI | 0.372563 | 1.799875 | 2.172439 | 1.923x | 0.330x | 8m41s | 72 |
| `glm-cc` | glm-5.2 | Claude Code CLI | 1.470253 | 0.890597 | 2.360850 | 2.089x | 1.301x | 8m34s | 72 |
| `gpt56-grok` | gpt-5.6-sol | Grok CLI | 1.209069 | 1.374873 | 2.583942 | 2.287x | 1.070x | 12m02s | 72 |
| `opus48-grok` | claude-opus-4-8 | Grok CLI | 1.253729 | 1.530256 | 2.783984 | 2.464x | 1.110x | 8m13s | 72 |
| `claude-native` | claude-fable-5 | Claude Code CLI | 4.472366 | 0.831390 | 5.303756 | 4.694x | 3.958x | 8m27s | 82 |

`claude-native` pins no model, so it ran the Claude Code CLI's own default,
`claude-fable-5`. That is a frontier-priced model and explains why it is the
costliest row: the lane id names a harness, not a price tier.

Proxy-routed lanes (`glm-grok`, `gpt56-grok`, `opus48-grok`, `sonnet5-grok`,
`glm-codex`, `grok45-codex`) carry imputed cost: the local proxy reports no
pricing, so those figures come from the price table rather than from the vendor.
They are marked `imputed` in the trace metadata.

## What the numbers say

**Orchestration lost on cost, unanimously.** All eleven lanes cost more than not
orchestrating. The cheapest total was 1.18x the baseline. This is the fourth
consecutive run in this series to reach the same conclusion on a well-specified
single-session task, now across a much wider matrix.

**The architect is the floor.** Architect overhead ranged $0.78 to $1.87 and was
the majority of most legs. Ranked by implementation cost alone the table reorders
completely, and six lanes beat the baseline on `lane $`. None beat it on total.
`glm-grok` is the clean demonstration: the cheapest implementation in the matrix
at $0.17, or 0.151x the baseline, still finished at 1.81x once its architect was
counted. A cheaper lane cannot buy back a fixed toll.

**Harness choice moves cost as much as model choice.** `glm-5.2` cost $0.17
through the grok CLI, $0.478 through codex, and $1.47 through the Claude CLI:
8.6x on one model doing identical work. Across the matrix, implementation cost
spanned 26x. This is the variable public model benchmarks cannot see, and the
reason a live dispatch is worth running.

**The spread bought nothing.** Every lane passed the same gate, landing between
72 and 97 tests. The most expensive lane was not the best one, and the cheapest
implementation tied the baseline on test count.

**Wall clock did not track cost.** `glm-grok` was cheapest to implement and
slowest overall at 22m41s. `codex-gpt56` finished in 5m10s. Serial legs mean an
eleven-lane sweep is the sum, not the max.

## Limitations

- **One dispatch per lane.** No variance, no error bars. Wall clock for identical
  work ranged 5m to 23m, so adjacent rows are ties, not rankings. A repeat run
  could reorder neighbours.
- **One task, one shape.** A well-specified single-session build with a
  deterministic gate is the case where orchestration is least likely to pay. It
  says nothing about work that exceeds one context window or spans repositories.
- **Prices decay.** Rates change and the table itself carries expiry notes.
  Ratios age better than dollars.
- **Imputed rows depend on the price table**, not on vendor-reported cost.
- **Quality was measured by a gate, not by review.** Test counts are a coarse
  proxy; the gate proves the contract holds, not that the code is good.

## Reproducing this

```shell
ab-run --task "<your task>" --target <seed dir> \
       --experiment <one id per lane> --lane <lane-id> --skip-solo \
       --pitwall-model claude-sonnet-5 \
       --verify "<your gate command>"
```

Then run one baseline leg with `--skip-pitwall` under its own experiment id.

Four things that matter more than they look:

1. **One experiment id per leg.** Ingest is additive and refuses a second write
   to the same leg, because re-ingesting would double-count.
2. **Always pass `--verify`.** A leg that fails is cheap, and its own report will
   still read as success. Cost is only comparable between legs that passed.
3. **Hold the architect constant.** Otherwise lane differences hide inside
   architect variance, which is the larger term.
4. **Run legs serially.** Concurrent legs contend on a shared local proxy and
   corrupt the wall-clock measurement.

Langfuse is optional. `pitwall_trace.py ingest-lane --dry-run` prints the priced
trace as JSON with no server running; only posting and the cross-leg report need
an instance. Measuring is not free: N lanes is N paid runs plus an architect
each, and captures contain full prompt and response text.

## Instrumentation notes

Four measurement bugs surfaced during this run. They are worth naming because
anyone building multi-vendor agent cost telemetry will meet the same class of
problem, where the receipt reads as complete while under-reporting.

1. **Proxy-routed harnesses report no cost.** The parser required the harness
   cost field, so four lanes ingested as $0.000000 while plainly burning tokens.
   Cost is now imputed from the price table and the row marked `imputed`. A zero
   cost with non-zero usage is treated as a placeholder, not as free.
2. **One dead capture aborted a whole leg.** A single zero-byte file discarded
   the cost of every healthy sibling capture. Dead captures are now skipped and
   named, while a capture that can be read but not priced stays fatal: it
   carries real spend and must never be dropped silently.
3. **A dispatch wrote its receipt outside the experiment directory** and its cost
   vanished from the leg while its work passed the gate. Dispatch sidecars are
   now reconciled against captures and any orphan is reported.
4. **The timeout cap silently did not exist** on a machine with no `timeout`
   binary, so lanes ran uncapped. Dispatches now run under a portable watchdog.

A fifth was not a measurement bug but invalidated a result: the harness denied
every file write for one lane because the working tree sat under `~/.claude`, a
protected path. That lane spent money and produced nothing, which in a cost table
looks indistinguishable from a bargain. Work trees now default outside it. The
general lesson is the one in point 2 of the reproduction list: without a gate, a
failed lane is the cheapest lane.

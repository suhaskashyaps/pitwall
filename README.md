<div align="center">

# pitwall

**A test bench for model-harness lanes: your session specs, routes, and verifies; the lane you pick writes the code.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://code.claude.com/docs)

</div>

## The headline run

The same seeded task, run twice on 2026-07-26: once as a solo Claude Code session, once as a pitwall architect plus one lane. Both legs passed the same verification gate before costs were compared.

| leg | model · harness | input | cache_read | cache_write | output | cost USD |
|---|---|---|---|---|---|---|
| solo (control) | claude-fable-5 · claude | 18 | 481,198 | 151,023 | 23,456 | 4.674638 |
| pitwall total | the two rows below | 124,106 | 1,700,724 | 121,244 | 41,324 | 1.500958 |
| - architect | claude-sonnet-5 · claude | 30 | 493,300 | 121,244 | 12,753 | 0.887608 |
| - lane | glm-5.2 · codex | 124,076 | 1,207,424 | 0 | 28,571 | 0.613349 |

The orchestrated leg cost 0.32x the control: the implementation tokens landed on glm-5.2 pricing instead of the control's claude-fable-5, and that gap absorbed the architect's $0.89. Read it alongside the variance finding below before concluding anything: this control ran a pricier model than the S8 control (claude-fable-5 vs claude-sonnet-5), and it is one run of the one lane the three-repeat round had already found cheaper than its control on all three runs. Reproduce the shape of this table on your own task with the bake-off recipe under [Usage](#usage).

## The lane that separated

Two experiments on the same seeded task: a sweep across every configured lane, one run each ([docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md)), then three repeats of three lanes plus three repeats of the no-orchestration control ([docs/experiments/s8-variance.md](docs/experiments/s8-variance.md)). One lane out of eleven separated: `glm-codex` (glm-5.2 · codex) was the cheapest lane in the single-run sweep (still 1.18x its baseline), and in the three-repeat round it was the only lane whose cost range sat entirely below the control's; the other repeated lanes overlapped it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/experiments/img/s8-cost-variance-dark.svg">
  <img alt="Cost to complete the same task once, three runs per lane plus three runs of the no-orchestration control. Each dot is one run, the bar spans that lane's cheapest to priciest run, the vertical tick is its mean, and the shaded column is the control's own range. Only glm-codex sits entirely outside the control range." src="docs/experiments/img/s8-cost-variance-light.svg">
</picture>

One run per lane cannot rank lanes. Each lane varied 1.46x to 1.85x against itself while adjacent lane means sat $0.24 to $0.27 apart, and rank order flipped between rounds, so a single measurement of a lane and its neighbour tells you nothing about which is cheaper.

## What pitwall is

Your session is the architect: it decomposes work, writes specs, and judges evidence. Lanes write the code. A lane is a config entry naming a **model-harness**: a model paired with the CLI harness that drives it (xAI's Grok CLI, OpenAI's Codex CLI, Anthropic's Claude Code CLI). Every vendor now ships its own agentic CLI, and the only way to know how a model-harness combination behaves on *your* tasks is to run it. Third-party models join through direct Anthropic-compatible endpoints or through [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), a proxy you run locally.

Model routers like claude-code-router swap the model behind your session's API calls, and aider's architect mode splits planning from editing inside one tool. Neither treats other vendors' own agentic CLIs as delegation targets. Pitwall does: each lane is a real harness with its own agentic loop, every task carries a five-part spec (objective, files, interfaces, constraints, verification), and every result is independently verified before the architect accepts it. You name a lane and hand over a spec; the `lane-runner` agent drives that model-harness headlessly, verifies the result itself, and reports evidence. Here, `glm-grok` (a GLM model on xAI's CLI, routed through the local proxy) builds a rate limiter:

```
LANE REPORT (glm-grok)
MODEL-HARNESS: glm-5.2 on the grok harness
STATUS: complete
OBJECTIVE: Thread-safe token-bucket rate limiter, stdlib only, with a fake-clock test suite.
CHANGES: ratelimit.py: TokenBucket: lazy refill, capacity-capped, lock-guarded, injectable clock.
         test_ratelimit.py: 4 tests: burst-then-denial, refill, idle cap, 8-thread concurrency.
VERIFIED: re-ran `python3 test_ratelimit.py` myself → 4/4 tests passed
HARNESS SAID: wrote both files, no shell attempted (matches the diff). stopReason was EndTurn.
GAPS: none.
```

The architect session never typed the code, and it doesn't take the lane's word for the result (`stopReason` is the harness's own turn-end signal, one of the gates `lane-runner` checks before believing anything). Adding a model-harness is one JSON entry.

Pitwall is not a guaranteed cost or quality optimizer. In A/B runs on well-specified single-repo builds the orchestration layer lost on speed and quality, and most lanes lost or tied on cost. Use it to find and verify the pairing that wins on your own work, not because delegation is presumed cheaper or better.

## What we learned

- **Harness choice moves cost as much as model choice.** The same model, run through three different CLI harnesses, spanned roughly an order of magnitude in cost on identical work (8.6x on one model). No model-level benchmark captures this, which is the gap this tool exists to fill: shortlist the model from public evals, then measure the pairing yourself.
- **Cost is meaningless without a gate.** Mid-sweep, the two cheapest-looking legs were cheap because they had failed: one never reached its vendor, the other was blocked from writing files and produced nothing. Both looked like bargains in the cost column. A lane that does no work always wins on price, and a leg's own report will still call it a success. Pass `--verify` so a cost is only comparable once its gate passed, and re-run the gate yourself rather than believing the leg.
- **Orchestration has to clear the architect's cost before a cheaper lane pays you back.** Every orchestrated leg pays two models: an architect that plans and delegates, and a lane that implements. The architect is not a fixed toll (it ranged $0.78 to $1.66 across repeats of the same three lanes) and it is frequently the majority of a leg. In the single-run sweep every lane cost more than not orchestrating; only in the three-repeat round did one lane out of eleven, `glm-codex`, come in below the control on every run. Orchestrate a task because it is too large for one session, not because delegation is presumed cheaper.
- **Measure your own tasks, and repeat the measurement.** Run at least three repeats per lane before believing a gap, and treat overlapping ranges as ties; a single-run cost table, ours included, ranks noise.

## Dependencies

The first two rows are the minimum setup: Claude Code itself doubles as the CLI behind the three claude-harness lanes, so with `jq` installed you already have a working lane (`claude-native`). Each row after that unlocks more lanes: install only what your lanes need. Preflight reports missing binaries and env vars; proxy connectivity and grok model blocks are separate checks.

| Dependency | Unlocks | Get it |
|---|---|---|
| Claude Code, with plugin support | the plugin itself, plus the 3 claude-harness lanes | [claude.com/claude-code](https://claude.com/claude-code) |
| jq | preflight, and validating grok-harness results | `brew install jq` |
| Grok CLI, authenticated | the 5 grok-harness lanes, incl. the default | [x.ai/cli](https://x.ai/cli) |
| Codex CLI, authenticated | the 3 codex-harness lanes | [openai/codex](https://github.com/openai/codex) |
| CLIProxyAPI running on port 8317 | the 6 proxy-routed lanes | [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) |
| Model blocks in `~/.grok/config.toml` | the 4 grok-harness proxy lanes | copy [the shipped template](config/grok-config.example.toml) |
| z.ai / Moonshot API keys | `glm-cc`, `kimi-cc` | create in each vendor's console, add to `~/.claude/.env` |
| uv | the cost tooling: `ab-run`, `pitwall_trace.py`, `pitwall_compare.py`, tests | [astral.sh/uv](https://docs.astral.sh/uv/) |
| Docker | optional: the local Langfuse stack in `observability/langfuse/` | [docker.com](https://www.docker.com) |
| coreutils, for `gtimeout` | optional: a native timeout binary. Without it lanes still get capped by a built-in watchdog | `brew install coreutils` |

Two steps are human-only: creating vendor API keys and each CLI's sign-in flow. A coding agent running this setup should hand those back to you.

## What you get

- **`orchestration` skill**: the routing doctrine: gate on task shape first (when *not* to orchestrate), decompose, write five-part specs, route each task to a chosen lane, verify evidence, consult the advisor at commitment boundaries.
- **`lane-runner` agent**: one generic dispatcher. Resolves a lane from `lanes.json`, preflights, invokes headlessly with per-lane env, verifies independently, reports in the fixed `LANE REPORT` format naming the model-harness.
- **`fable-advisor` agent**: a read-only second-opinion advisor for commitment boundaries; it advises, never implements.
- **`lanes.json`**: the fleet, in user config. Add, remove, or repoint lanes by editing one file.
- **`scripts/ab-run`**: runs one task twice under a single experiment id (pinned lane vs plain session), records per-leg wall clock and harness exit, and re-runs your acceptance command with `--verify`.
- **`scripts/pitwall_trace.py`**: turns each harness's usage capture into priced, comparable cost. Imputes from `config/prices.json` when a harness reports none (proxy-routed lanes never do), marks those rows `imputed`, refuses double-ingest, and names any dispatch whose capture never landed.
- **`scripts/pitwall_compare.py`**: joins several single-lane experiments plus a baseline into one table of cost, wall clock and gate result. This is the bake-off.
- **`scripts/preflight-all.sh`**: a lane health matrix that blocks lanes whose binary, credentials, proxy, or price entry are missing before you spend anything.

Langfuse is optional, and know what you are signing up for before starting it: the local stack is six containers (web, worker, Postgres, ClickHouse, Redis, MinIO) that hold multiple GB of RAM for as long as they run and will noticeably slow a laptop. Nothing in the core loop needs it — lane dispatch, verification, and `ab-run`'s legs and gates all run without it (`ab-run` says so and skips trace ingest when no `LANGFUSE_*` config is present, retaining the run data for later ingest). Only storing traces and the cross-leg cost report need an instance; `pitwall_trace.py ingest-lane --dry-run` prints the priced trace as JSON with no server at all. The compose file ships in `observability/langfuse/` — tear the stack down when idle.

## Install

Install the [dependencies](#dependencies) your lanes need, then:

```bash
git clone https://github.com/suhaskashyaps/pitwall ~/.claude/plugins/pitwall
```

In Claude Code:

```
/plugin marketplace add ~/.claude/plugins/pitwall
/plugin install pitwall@pitwall
```

Restart Claude Code (or `/reload-plugins`), then run `/agents` and confirm `pitwall:lane-runner` is listed. The first dispatch seeds `~/.claude/pitwall/lanes.json` from the example automatically. To run preflight before any dispatch, copy it yourself:

```bash
mkdir -p ~/.claude/pitwall
cp ~/.claude/plugins/pitwall/config/lanes.example.json ~/.claude/pitwall/lanes.json
```

Three lanes authenticate natively and need no keys: `claude-native` works with nothing beyond Claude Code itself, while `grok` and `codex-gpt56` need their CLI installed and signed in through its own login flow. Shimmed lanes read credentials from `~/.claude/.env` (override with `PITWALL_ENV_FILE`); preflight and lane-runner load that file themselves, so secrets reach only the lane subprocess and never your ambient shell:

```bash
ZAI_API_KEY=…        ZAI_BASE_URL=…        # glm-cc (z.ai)
MOONSHOT_API_KEY=…   MOONSHOT_BASE_URL=…   # kimi-cc (Moonshot)
CLIPROXY_API_KEY=…                            # the 6 proxy-routed lanes
```

For the proxy-routed lanes: install and start [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) with upstream accounts for the models you want it to serve (its README covers that). Confirm it answers: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8317/` should print `200`. Then copy `config/grok-config.example.toml` to `~/.grok/config.toml` as-is. Skip all of this if you only use the direct lanes. Details: [docs/lanes.md](docs/lanes.md). Then check the fleet:

```bash
~/.claude/plugins/pitwall/scripts/preflight-all.sh
```

Every lane you plan to use should show `ok`/`ok`; with all eleven configured, the footer reads `11/11 lanes ready`. A lane reporting `MISSING(VAR)` means that credential is absent from your env file: correct reporting, not a bug; add the variable and re-run. Preflight checks binaries and env vars only; it does not probe the proxy. Full runbook: [docs/verification.md](docs/verification.md).

## Usage

Dispatch by asking your session to hand a spec to the agent. In Claude Code, type:

```
Dispatch this to the pitwall:lane-runner agent:

LANE: claude-native

Objective: Create /tmp/pitwall-test/health.py containing a function
health() that returns the string "ok".

Files: create /tmp/pitwall-test/health.py

Interfaces:
def health() -> str:
    return "ok"

Constraints: one file, one function, work in /tmp/pitwall-test.

Verification: cd /tmp/pitwall-test && python3 -c "from health import health; assert health() == 'ok'; print('PASS')"
```

The session spawns `lane-runner` with the spec as its prompt. `LANE: claude-native` makes this work on the minimum setup: swap in any lane from your fleet. The dispatch succeeded when the report returns `STATUS: complete` and `VERIFIED:` quotes your verification command's own output. `STATUS: unavailable` names the exact missing piece: fix it, or re-dispatch to another lane. For multi-task builds, invoke the `pitwall:orchestration` skill and let the session route: independent specs fan out to parallel lanes, correctness-critical work goes cross-vendor, and high-stakes work races two lanes on the same spec.

Add a lane by editing `~/.claude/pitwall/lanes.json` (no plugin change):

```json
"glm-cc": {
  "harness": "claude",
  "model": "glm-5.2",
  "description": "GLM 5.2 through the claude CLI via z.ai",
  "env": { "ANTHROPIC_BASE_URL": "ZAI_BASE_URL", "ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY" },
  "capabilities": ["edit"]
}
```

`env` values are env-var *names*, never secrets: `"ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY"` means "read `$ZAI_API_KEY` from the env file and inject it as `ANTHROPIC_AUTH_TOKEN`". The JSON is safe to commit. Full schema and per-harness wiring rules: [docs/lanes.md](docs/lanes.md).

### Running a bake-off

```bash
# one leg per lane, plus a baseline, each under its own experiment id
scripts/ab-run --task "$(cat task.md)" --target ./seed \
  --experiment bake-glm-codex --lane glm-codex --skip-solo \
  --pitwall-model claude-sonnet-5 \
  --verify "pytest -q"

scripts/ab-run --task "$(cat task.md)" --target ./seed \
  --experiment bake-baseline --skip-pitwall \
  --verify "pytest -q"

scripts/pitwall_compare.py \
  "baseline=bake-baseline=solo" \
  "glm-codex=bake-glm-codex=lane" \
  --verify "pytest -q"
```

One experiment id per leg: ingest is additive and refuses a second write to the same leg. Always pass `--verify`, because a lane that fails is the cheapest lane on the table and its own report will still read as success. Hold `--pitwall-model` constant across legs, since architect cost dominates and a varying architect hides the lane difference. Measuring is not free: N lanes is N paid runs plus an architect each, and legs run serially by design. A worked example across every shipped lane, with method and limitations: [docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md).

## Shipped lanes

| Lane | Model | Harness | Auth |
|---|---|---|---|
| `grok` | (CLI default) | Grok CLI (xAI) | native, no API key |
| `codex-gpt56` | gpt-5.6-sol | Codex CLI | native |
| `claude-native` | (CLI default) | Claude Code CLI | native |
| `glm-cc` | glm-5.2 | Claude Code CLI | z.ai via env shim |
| `kimi-cc` | kimi-k3 | Claude Code CLI | Moonshot via env shim |
| `glm-grok` | glm-5.2 | Grok CLI | CLIProxyAPI via `~/.grok/config.toml` |
| `gpt56-grok` | gpt-5.6-sol | Grok CLI | CLIProxyAPI via `~/.grok/config.toml` |
| `opus48-grok` | claude-opus-4-8 | Grok CLI | CLIProxyAPI via `~/.grok/config.toml` |
| `sonnet5-grok` | claude-sonnet-5 | Grok CLI | CLIProxyAPI via `~/.grok/config.toml` |
| `glm-codex` | glm-5.2 | Codex CLI | CLIProxyAPI via `model_providers` flags |
| `grok45-codex` | grok-4.5 | Codex CLI | CLIProxyAPI via `model_providers` flags |

### Cost notes

To pick a model for a lane, start from [Artificial Analysis](https://artificialanalysis.ai): its Intelligence Index scores models on a common eval battery, and its cost-to-run-the-index figure works as a $/task proxy. A model earns a lane when it clears the quality bar for your task class at the lowest cost per task. Benchmarks shortlist the model; a live dispatch through the lane picks the harness (see [What we learned](#what-we-learned)). Two traps that cost real money and are invisible from the config alone:

- Codex silently defaults an unrecognized model to `xhigh` reasoning effort, which can burn an order of magnitude more tokens than the same task needs. Pin `model_reasoning_effort` on every codex lane; the shipped lanes already do.
- `kimi-k3` omits trailing newlines on files it writes. Verification commands that exact-match `\n`-terminated strings fail against it; compare trimmed content.

The full sweep lives in [docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md): every lane, one dispatch each, architect held constant at `claude-sonnet-5`, all legs gate-passed. Every lane cost more than not orchestrating (cheapest total 1.18x baseline), and harness choice moved one model's implementation cost 8.6x.

## Alternatives

- [claude-code-router](https://github.com/musistudio/claude-code-router) routes the API requests behind your session and wins on infrastructure: fallbacks, key rotation, per-request observability, a web UI. It has no concept of specs, lanes, or an architect verifying a diff; the reasoning stays in whatever agent you're sitting in.
- [aider's architect/editor mode](https://aider.chat/docs/usage/modes.html) is the same delegation idea, built-in and zero-config, with a proven per-edit split. The split lives inside one tool at one API layer: no independent agentic harnesses, no separate verification step, and you leave the Claude Code environment.
- Claude Code's native subagents give per-agent model selection with zero external dependencies, and pitwall builds on them. Alone, they stay within Anthropic models and enforce no spec or verification contract.

Pitwall's trade: cross-vendor agentic harnesses as first-class delegation targets with enforced verification, at the cost of installing and authenticating each lane's CLI, and bringing your own gateway for proxy lanes.

## Docs

- [docs/architecture.md](docs/architecture.md): the design rationale and invariants
- [docs/lanes.md](docs/lanes.md): full `lanes.json` schema, per-harness wiring, proxy setup
- [docs/verification.md](docs/verification.md): install-verification runbook, including the live dispatch test
- [docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md): the eleven-lane cost sweep, one run each, with method and caveats
- [docs/experiments/s8-variance.md](docs/experiments/s8-variance.md): three repeats per lane, showing which of those differences survive

## Contributing, license, credits

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT: see [LICENSE](LICENSE).

Pitwall's primary inspiration is [Omnigent](https://github.com/omnigent-ai/omnigent), the meta-harness that treats coding-agent harnesses as swappable parts. The code began as a fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor), moving the lane inventory from hardcoded agent files into user config. If you still have the upstream plugin installed, disable it first: both define an agent named `fable-advisor` and a skill named `orchestration`.

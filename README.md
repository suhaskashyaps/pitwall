<div align="center">

# pitwall

**A test bench for model-harness lanes: your session specs, routes, and verifies; the lane you pick writes the code.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://code.claude.com/docs)

</div>

Your session is the architect: it decomposes work, writes specs, and judges evidence. Lanes write the code. A lane is a config entry naming a **model-harness**: a model paired with the CLI harness that drives it (xAI's Grok CLI, OpenAI's Codex CLI, Anthropic's Claude Code CLI). Third-party models join through direct Anthropic-compatible endpoints or through [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), a proxy you run locally. You name a lane and hand over a spec; the `lane-runner` agent drives that model-harness headlessly, verifies the result itself, and reports evidence. Here, `glm-grok` (a GLM model on xAI's CLI, routed through the local proxy) builds a rate limiter:

```
LANE REPORT (glm-grok)
MODEL-HARNESS: glm-5.2 on the grok harness
STATUS: complete
OBJECTIVE: Thread-safe token-bucket rate limiter, stdlib only, with a fake-clock test suite.
CHANGES: ratelimit.py — TokenBucket: lazy refill, capacity-capped, lock-guarded, injectable clock.
         test_ratelimit.py — 4 tests: burst-then-denial, refill, idle cap, 8-thread concurrency.
VERIFIED: re-ran `python3 test_ratelimit.py` myself → 4/4 tests passed
HARNESS SAID: wrote both files, no shell attempted — matches the diff. stopReason was EndTurn.
GAPS: none.
```

The architect session never typed the code, and it doesn't take the lane's word for the result (`stopReason` is the harness's own turn-end signal, one of the gates `lane-runner` checks before believing anything).

## Why this exists

Every vendor now ships its own agentic CLI, and the only way to know how a model-harness combination behaves on *your* tasks is to run it. Pitwall makes that a one-JSON-entry experiment. Model routers like claude-code-router swap the model behind your session's API calls, and aider's architect mode splits planning from editing inside one tool. Neither treats other vendors' own agentic CLIs as delegation targets. Pitwall does: each lane is a real harness with its own agentic loop, every task carries a five-part spec (objective, files, interfaces, constraints, verification), and every result is independently verified before the architect accepts it. Adding a model-harness is one JSON entry.

**What pitwall is not: a cost or quality optimizer.** In our own A/B runs on well-specified single-repo builds, the orchestration layer *lost* on cost, speed, and quality compared to doing the task solo in one session, regardless of which model played architect. Coordination output, lane latency, and multi-lane authorship are overhead the task must be large enough to absorb. Use pitwall to try model-harness combinations and measure what happens on your own work, not because delegation is presumed cheaper or better. See [Findings](#findings) for the run that measured it.

## Findings

Three results from running the same seeded task across every configured lane, one lane at a time, against a baseline session that used no orchestration. Numbers, method, and caveats: [docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md).

**The architect is the cost floor, not the lane.** Coordination overhead was the majority of most legs, and it does not shrink when you pick a cheaper lane. The cheapest implementation in the matrix still produced a leg that cost more than not orchestrating at all. This is the finding that should decide whether you orchestrate a given task: delegation has to clear a fixed toll before a cheaper model can pay you back.

**Harness choice moves cost as much as model choice.** The same model, run through three different CLI harnesses, spanned roughly an order of magnitude in cost on identical work. No model-level benchmark captures this, which is the gap this tool exists to fill: shortlist the model from public evals, then measure the pairing yourself.

**Cost is meaningless without a gate.** Mid-sweep, the two cheapest-looking legs were cheap because they had failed: one never reached its vendor, the other was blocked from writing files and produced nothing. Both looked like bargains in the cost column. A lane that does no work always wins on price, and a leg's own report will still call it a success. Pass `--verify` so a cost is only comparable once its gate passed, and re-run the gate yourself rather than believing the leg.

One caution on reading any of this, ours or yours: a single run per lane cannot rank neighbours. Wall clock for identical work varied by more than 2x between lanes, and list prices change under you. Treat close results as ties.

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
| coreutils, for `gtimeout` | optional: caps lane runtime | `brew install coreutils` |

Two steps are human-only: creating vendor API keys and each CLI's sign-in flow. A coding agent running this setup should hand those back to you.

## What you get

- **`orchestration` skill**: the routing doctrine: gate on task shape first (it tells you when *not* to orchestrate), decompose, write five-part specs, route each task to a deliberately chosen lane, verify evidence, consult the advisor at commitment boundaries.
- **`lane-runner` agent**: one generic dispatcher. Resolves a lane from `lanes.json`, preflights the harness, invokes it headlessly with per-lane env, verifies independently, reports in the fixed `LANE REPORT` format: every report names the model-harness it ran.
- **`fable-advisor` agent**: a read-only second-opinion advisor for commitment boundaries. It advises; it never implements.
- **`lanes.json`**: the fleet, in user config. Add, remove, or repoint lanes by editing one file.

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

Restart Claude Code (or `/reload-plugins`), then run `/agents` and confirm `pitwall:lane-runner` is listed.

The first dispatch seeds `~/.claude/pitwall/lanes.json` from the example automatically. To run preflight before any dispatch, copy it yourself:

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

For the proxy-routed lanes: install and start [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) with upstream accounts for the models you want it to serve (its README covers that). Confirm it answers: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8317/` should print `200`. Then copy `config/grok-config.example.toml` to `~/.grok/config.toml` as-is. Skip all of this if you only use the direct lanes. Details: [docs/lanes.md](docs/lanes.md).

Then check the fleet:

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

The session spawns `lane-runner` with the spec as its prompt. `LANE: claude-native` makes this work on the minimum setup: swap in any lane from your fleet. The dispatch succeeded when the report returns `STATUS: complete` and `VERIFIED:` quotes your verification command's own output. `STATUS: unavailable` names the exact missing piece: fix it, or re-dispatch to another lane.

For multi-task builds, invoke the `pitwall:orchestration` skill and let the session route: independent specs fan out to parallel lanes, correctness-critical work goes cross-vendor, and high-stakes work races two lanes on the same spec.

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

To pick a model for a lane, start from [Artificial Analysis](https://artificialanalysis.ai): its Intelligence Index scores models on a common eval battery, and its cost-to-run-the-index figure works as a $/task proxy. A model earns a lane when it clears the quality bar for your task class at the lowest cost per task. Benchmarks shortlist the model; a live dispatch through the lane picks the harness (see [Findings](#findings)).

Two traps that cost real money and are invisible from the config alone:

- Codex silently defaults an unrecognized model to `xhigh` reasoning effort, which can burn an order of magnitude more tokens than the same task needs. Pin `model_reasoning_effort` on every codex lane; the shipped lanes already do.
- `kimi-k3` omits trailing newlines on files it writes. Verification commands that exact-match `\n`-terminated strings fail against it; compare trimmed content.

Every configured lane on one seeded build task (a 12-resource registry with referential integrity behind a deterministic gate), one dispatch each, architect held constant at `claude-sonnet-5`, against a baseline session that used no orchestration. All twelve legs passed both gates. Prices as of 2026-07-26.

The first row is the baseline: one ordinary Claude Code session doing the whole
task itself, no lanes, no architect. Every other row delegated all implementation
to the named model-harness while `claude-sonnet-5` played architect.

| lane | model | harness | lane $ | architect $ | total $ | vs baseline | wall clock |
|---|---|---|---|---|---|---|---|
| *no orchestration* | *claude-sonnet-5* | *Claude Code* | *n/a* | *n/a* | *1.13* | *1.00x* | *4m02s* |
| `glm-codex` | glm-5.2 | Codex CLI | 0.48 | 0.86 | 1.34 | 1.18x | 9m15s |
| `codex-gpt56` | gpt-5.6-sol | Codex CLI | 0.65 | 0.78 | 1.43 | 1.26x | 5m10s |
| `grok45-codex` | grok-4.5 | Codex CLI | 0.47 | 1.04 | 1.52 | 1.34x | 6m50s |
| `sonnet5-grok` | claude-sonnet-5 | Grok CLI | 0.67 | 0.98 | 1.65 | 1.46x | 8m25s |
| `kimi-cc` | kimi-k3 | Claude Code CLI | 0.83 | 0.88 | 1.71 | 1.52x | 9m01s |
| `glm-grok` | glm-5.2 | Grok CLI | **0.17** | 1.87 | 2.04 | 1.81x | 22m41s |
| `grok` | grok-4.5-build | Grok CLI | 0.37 | 1.80 | 2.17 | 1.92x | 8m41s |
| `glm-cc` | glm-5.2 | Claude Code CLI | 1.47 | 0.89 | 2.36 | 2.09x | 8m34s |
| `gpt56-grok` | gpt-5.6-sol | Grok CLI | 1.21 | 1.37 | 2.58 | 2.29x | 12m02s |
| `opus48-grok` | claude-opus-4-8 | Grok CLI | 1.25 | 1.53 | 2.78 | 2.46x | 8m13s |
| `claude-native` | claude-fable-5 | Claude Code CLI | 4.47 | 0.83 | 5.30 | 4.69x | 8m27s |

How to read it:

- **Every lane cost more than not orchestrating.** The cheapest total still ran 1.18x the baseline. Sort by `lane $` and the ordering changes completely, which is the point: the architect column is the toll, and it does not shrink when you pick a cheaper lane. `glm-grok` had the cheapest implementation in the matrix at $0.17 and still finished 1.81x.
- **Harness choice moved cost 8.6x on one model.** Read the three `glm-5.2` rows: $0.17 through the Grok CLI, $0.48 through Codex, $1.47 through the Claude Code CLI, on identical work. Lane cost overall spanned 26x. No model-level benchmark captures this.
- **The spread bought no quality.** All twelve passed the same gate, landing between 72 and 97 tests. The costliest lane, frontier-priced `claude-fable-5`, was not the best one; the cheapest implementation matched the baseline's test count.
- Proxy-routed lanes report no cost of their own, because the proxy knows no pricing. Pitwall imputes those from `config/prices.json` and marks the row `imputed`, so a stale price table silently skews exactly those lanes.
- Single samples. Wall clock for identical work ranged 5m to 23m, so treat neighbouring rows as ties and re-measure on your own task before acting.

## Alternatives

- [claude-code-router](https://github.com/musistudio/claude-code-router) routes the API requests behind your session and wins on infrastructure: fallbacks, key rotation, per-request observability, a web UI. It has no concept of specs, lanes, or an architect verifying a diff: the reasoning stays in whatever agent you're sitting in.
- [aider's architect/editor mode](https://aider.chat/docs/usage/modes.html) is the same delegation idea, built-in and zero-config, with a proven per-edit split. The split lives inside one tool at one API layer: no independent agentic harnesses, no separate verification step, and you leave the Claude Code environment.
- Claude Code's native subagents give per-agent model selection with zero external dependencies, and pitwall builds on them. Alone, they stay within Anthropic models and enforce no spec or verification contract.

Pitwall's trade: cross-vendor agentic harnesses as first-class delegation targets with enforced verification, at the cost of installing and authenticating each lane's CLI, and bringing your own gateway for proxy lanes.

## Docs

- [docs/architecture.md](docs/architecture.md): the design rationale and invariants
- [docs/lanes.md](docs/lanes.md): full `lanes.json` schema, per-harness wiring, proxy setup
- [docs/verification.md](docs/verification.md): install-verification runbook, including the live dispatch test
- [docs/experiments/s7-lane-cost.md](docs/experiments/s7-lane-cost.md): the lane-cost run behind [Findings](#findings), with method and caveats

## Contributing, license, credits

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT: see [LICENSE](LICENSE).

Pitwall's primary inspiration is [Omnigent](https://github.com/omnigent-ai/omnigent), the meta-harness that treats coding-agent harnesses as swappable parts. The code began as a fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor), moving the lane inventory from hardcoded agent files into user config. If you still have the upstream plugin installed, disable it first: both define an agent named `fable-advisor` and a skill named `orchestration`.

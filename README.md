<div align="center">

# pitwall

**A frontier architect specs, routes, and verifies; the best $/task model-harness does the typing.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Claude Code plugin](https://img.shields.io/badge/Claude%20Code-plugin-d97757.svg)](https://code.claude.com/docs)

</div>

Your session runs the expensive model as an architect: it decomposes work, writes specs, and judges evidence. The typing happens in lanes. A lane is a config entry naming a **model-harness**: a model paired with the CLI harness that drives it: xAI's Grok CLI, OpenAI's Codex CLI, Anthropic's Claude Code CLI. Third-party models join either through direct Anthropic-compatible endpoints or through [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI), a separate proxy you run locally. You name a lane and hand over a spec; the `lane-runner` agent drives that model-harness headlessly, verifies the result itself, and reports evidence. Here, `glm-grok` (a GLM model on xAI's CLI, routed through the local proxy) builds a rate limiter:

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

A frontier-model session spends most of its tokens typing code that doesn't need frontier judgment. The judgment (decomposition, interface design, verdicts on diffs) is worth the premium; the volume is not. Model routers like claude-code-router swap the model behind your session's API calls, and aider's architect mode splits planning from editing inside one tool. Neither treats other vendors' own agentic CLIs as delegation targets. Pitwall does: each lane is a real harness with its own agentic loop, every task carries a five-part spec (objective, files, interfaces, constraints, verification), every result is independently verified before the architect accepts it, and adding a model-harness is one JSON entry.

## Dependencies

The first two rows are the whole minimum setup: Claude Code itself doubles as the CLI behind the three claude-harness lanes, so with `jq` installed you already have a working lane (`claude-native`). Each row after that unlocks more lanes: install only what your lanes need. Preflight reports missing binaries and env vars; proxy connectivity and grok model blocks are separate checks.

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

- **`orchestration` skill**: the routing doctrine: decompose, write five-part specs, route each task to the best $/task lane that's adequate for it, verify evidence, consult the advisor at commitment boundaries.
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

For the proxy-routed lanes: install and start [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) with upstream accounts for the models you want it to serve (its README covers that), confirm it answers: `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8317/` should print `200`, then copy `config/grok-config.example.toml` to `~/.grok/config.toml` as-is. Skip all of this if you only use the direct lanes. Details: [docs/lanes.md](docs/lanes.md).

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

Add a lane by editing `~/.claude/pitwall/lanes.json`: no plugin change:

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

To pick a model for a lane, start from [Artificial Analysis](https://artificialanalysis.ai): its Intelligence Index scores models on a common eval battery, and its cost-to-run-the-index figure works as a $/task proxy. A model earns a lane when it clears the quality bar for your task class at the lowest cost per task. Then measure on your own harnesses: in our samples, harness choice moved cost more than model choice, which no model-level benchmark captures. Benchmarks shortlist the model; a live dispatch through the lane picks the harness.

Measured once, on one machine, on the same trivial write task: directional, not a benchmark:

- `claude-opus-4-8` used 143k tokens through the codex harness versus 67k through the grok harness on a single trivial write task. That result motivated pruning the Anthropic-on-codex pairings; harness choice moved cost more than model choice.
- Codex defaults unrecognized models to `xhigh` reasoning effort; on the same task `grok-4.5` burned 96k tokens against `glm-5.2`'s 5.6k until pinned. Both proxy-routed codex lanes, `glm-codex` and `grok45-codex`, pin `model_reasoning_effort = medium`; `codex-gpt56` pins `high`.
- `kimi-k3` omits trailing newlines on files it writes. Verification commands that exact-match `\n`-terminated strings fail against it; compare trimmed content.

## Alternatives

- [claude-code-router](https://github.com/musistudio/claude-code-router) routes the API requests behind your session and wins on infrastructure: fallbacks, key rotation, per-request observability, a web UI. It has no concept of specs, lanes, or an architect verifying a diff: the reasoning stays in whatever agent you're sitting in.
- [aider's architect/editor mode](https://aider.chat/docs/usage/modes.html) is the same economic idea, built-in and zero-config, with a proven per-edit cost split. The split lives inside one tool at one API layer: no independent agentic harnesses, no separate verification step, and you leave the Claude Code environment.
- Claude Code's native subagents give per-agent model selection with zero external dependencies, and pitwall builds on them. Alone, they stay within Anthropic models and enforce no spec or verification contract.

Pitwall's trade: cross-vendor agentic harnesses as first-class delegation targets with enforced verification, at the cost of installing and authenticating each lane's CLI, and bringing your own gateway for proxy lanes.

## Docs

- [docs/architecture.md](docs/architecture.md): the design rationale and invariants
- [docs/lanes.md](docs/lanes.md): full `lanes.json` schema, per-harness wiring, proxy setup
- [docs/verification.md](docs/verification.md): install-verification runbook, including the live dispatch test

## Contributing, license, credits

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT: see [LICENSE](LICENSE).

Pitwall's primary inspiration is [Omnigent](https://github.com/omnigent-ai/omnigent), the meta-harness that treats coding-agent harnesses as swappable parts. The code began as a fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor), moving the lane inventory from hardcoded agent files into user config. If you still have the upstream plugin installed, disable it first: both define an agent named `fable-advisor` and a skill named `orchestration`.

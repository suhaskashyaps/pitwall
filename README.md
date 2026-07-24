# pitwall

A frontier architect specs, routes, and verifies; the best $/task model-harness does the typing.

Your session runs the expensive model as an architect: it decomposes work, writes specs, and judges evidence. The typing happens in lanes — each a named **model-harness**, a model paired with the CLI harness that drives it: xAI's `grok`, OpenAI's `codex`, Anthropic's `claude`, with third-party models (GLM, Kimi) reached through a local gateway. You name a lane and hand over a spec; the `lane-runner` agent drives that model-harness headlessly, verifies the result itself, and reports evidence:

```
LANE REPORT (grok)
MODEL-HARNESS: harness default on the grok harness
STATUS: complete
OBJECTIVE: Create /tmp/pitwall-test/health.py with a health() function returning "ok".
CHANGES: /tmp/pitwall-test/health.py — new file, defines def health() -> str (did not exist pre-dispatch).
VERIFIED: re-ran `python3 -c "from health import health; assert health() == 'ok'; print('PASS')"` myself → PASS
HARNESS SAID: "Created one file and verified it" — matches observed diff. stopReason was EndTurn.
GAPS: none.
```

The architect session never typed the code, and it doesn't take the lane's word for the result.

## Why this exists

A frontier-model session spends most of its tokens typing code that doesn't need frontier judgment. The judgment — decomposition, interface design, verdicts on diffs — is worth the premium; the volume is not. Model routers like claude-code-router swap the model behind your session's API calls, and aider's architect mode splits planning from editing inside one tool. Neither treats other vendors' own agentic CLIs as delegation targets. Pitwall does: each lane is a real harness with its own agentic loop, every task carries a five-part spec, every result is independently verified before the architect accepts it, and adding a model-harness is one JSON entry.

## Dependencies

The minimum working setup is the first three rows — Claude Code, `jq`, and one authenticated lane CLI. Everything below that depends on which lanes you enable; preflight reports exactly what's missing.

| Dependency | Needed by | Install |
|---|---|---|
| Claude Code with plugin support | everything | — |
| `jq` | preflight and the grok-lane success gate | `brew install jq` |
| [`grok`](https://x.ai/cli) CLI, authenticated | the 6 grok-harness lanes, including the default `grok` | x.ai/cli |
| `codex` CLI, authenticated | the 6 codex-harness lanes | OpenAI's Codex CLI |
| `claude` CLI | the 4 claude-harness lanes | already present with Claude Code |
| [CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) serving `127.0.0.1:8317` | 11 of the 16 shipped lanes | its README; those lanes fail at connect time without it |
| `[model.*]` blocks in `~/.grok/config.toml` | the 5 grok-harness proxy lanes | copy `config/grok-config.example.toml` |
| z.ai / Moonshot API keys in `~/.claude/.env` | `glm-cc` / `kimi-cc` | from each vendor |
| `coreutils` (`gtimeout`) | optional — caps lane runtime | `brew install coreutils` |

## What you get

- **`orchestration` skill** — the routing doctrine: decompose, write five-part specs, route each task to the best $/task lane that's adequate for it, verify evidence, consult the advisor at commitment boundaries.
- **`lane-runner` agent** — one generic dispatcher. Resolves a lane from `lanes.json`, preflights the harness, invokes it headlessly with per-lane env, verifies independently, reports in the fixed `LANE REPORT` format — every report names the model-harness it ran.
- **`fable-advisor` agent** — a read-only second-opinion advisor for commitment boundaries. It advises; it never implements.
- **`lanes.json`** — the fleet, in user config. Add, remove, or repoint lanes by editing one file.

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

Restart Claude Code (or `/reload-plugins`), then confirm `pitwall:lane-runner` appears in your agent list.

Create your lane config, or let the first dispatch seed it from the example:

```bash
mkdir -p ~/.claude/pitwall
cp ~/.claude/plugins/pitwall/config/lanes.example.json ~/.claude/pitwall/lanes.json
```

The three native lanes (`grok`, `codex-gpt56`, `claude-native`) need nothing else — they use each CLI's own auth. Shimmed lanes read credentials from `~/.claude/.env` (override with `PITWALL_ENV_FILE`); preflight and lane-runner load that file themselves, so secrets reach only the lane subprocess and never your ambient shell:

```bash
ZAI_API_KEY=…        ZAI_BASE_URL=…        # glm-cc (z.ai)
MOONSHOT_API_KEY=…   MOONSHOT_BASE_URL=…   # kimi-cc (Moonshot)
CLIPROXY_BASE_URL=…  CLIPROXY_API_KEY=…    # every proxy-routed lane
```

For the proxy-routed lanes, start CLIProxyAPI and copy `config/grok-config.example.toml` into `~/.grok/config.toml`. Skip both if you only use the direct lanes. Details: [docs/lanes.md](docs/lanes.md).

Then check the fleet:

```bash
~/.claude/plugins/pitwall/scripts/preflight-all.sh
```

A lane reporting `MISSING(VAR)` means that credential is absent from your env file — correct reporting, not a bug. Preflight checks binaries and env vars only; it does not probe the proxy. Full runbook: [docs/verification.md](docs/verification.md).

## Usage

Dispatch a task by sending the `lane-runner` agent a lane ID and a five-part spec:

```
LANE: grok

Objective: Create /tmp/pitwall-test/health.py containing a function
health() that returns the string "ok".

Files: create /tmp/pitwall-test/health.py

Interfaces:
def health() -> str:
    return "ok"

Constraints: one file, one function, work in /tmp/pitwall-test.

Verification: cd /tmp/pitwall-test && python3 -c "from health import health; assert health() == 'ok'; print('PASS')"
```

For multi-task builds, invoke the `pitwall:orchestration` skill and let the session route: independent specs fan out to parallel lanes, correctness-critical work goes cross-vendor, and high-stakes work races two lanes on the same spec.

Add a lane by editing `~/.claude/pitwall/lanes.json` — no plugin change:

```json
"glm-cc": {
  "harness": "claude",
  "model": "glm-5.2",
  "description": "GLM 5.2 through the claude CLI via z.ai",
  "env": { "ANTHROPIC_BASE_URL": "ZAI_BASE_URL", "ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY" },
  "capabilities": ["edit"]
}
```

`env` values are env-var *names*, never secrets — `"ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY"` means "read `$ZAI_API_KEY` from the env file and inject it as `ANTHROPIC_AUTH_TOKEN`". The JSON is safe to commit. Full schema and per-harness wiring rules: [docs/lanes.md](docs/lanes.md).

## Shipped lanes

| Lane | Harness | Model | Auth |
|---|---|---|---|
| `grok` | Grok Build CLI (xAI) | (CLI default) | native, no API key |
| `codex-gpt56` | codex CLI | gpt-5.6-sol | native |
| `claude-native` | claude CLI | (CLI default) | native |
| `glm-cc` | claude CLI | glm-5.2 | z.ai via env shim |
| `kimi-cc` | claude CLI | kimi-k3 | Moonshot via env shim |
| `gpt56-cc` | claude CLI | gpt-5.6-sol | CLIProxyAPI via env shim |
| `glm-grok` | Grok Build CLI | glm-5.2 | CLIProxyAPI via `~/.grok/config.toml` |
| `gpt56-grok` | Grok Build CLI | gpt-5.6-sol | CLIProxyAPI via `~/.grok/config.toml` |
| `kimi-grok` | Grok Build CLI | kimi-k3 | CLIProxyAPI via `~/.grok/config.toml` |
| `opus48-grok` | Grok Build CLI | claude-opus-4-8 | CLIProxyAPI via `~/.grok/config.toml` |
| `sonnet5-grok` | Grok Build CLI | claude-sonnet-5 | CLIProxyAPI via `~/.grok/config.toml` |
| `glm-codex` | codex CLI | glm-5.2 | CLIProxyAPI via `model_providers` flags |
| `grok45-codex` | codex CLI | grok-4.5 | CLIProxyAPI via `model_providers` flags |
| `kimi-codex` | codex CLI | kimi-k3 | CLIProxyAPI via `model_providers` flags |
| `opus48-codex` | codex CLI | claude-opus-4-8 | CLIProxyAPI via `model_providers` flags |
| `sonnet5-codex` | codex CLI | claude-sonnet-5 | CLIProxyAPI via `model_providers` flags |

`grok` is not `groq`: the `grok` harness drives xAI's Grok Build CLI with native auth. `lane-runner` also supports a `groq` harness (Groq Inc.'s HTTP API, a different vendor), but no such lane ships.

### Cost notes

Measured once, on one machine, on the same trivial write task — directional, not a benchmark:

- The same Anthropic model cost ~2x through the codex harness versus the grok harness (143k vs 67k tokens). Harness choice moved cost more than model choice.
- Codex defaults unrecognized models to `xhigh` reasoning effort; on the same task `grok-4.5` burned 96k tokens against `glm-5.2`'s 5.6k until pinned. The proxy-routed codex lanes pin `model_reasoning_effort = medium`; `codex-gpt56` pins `high`.
- `kimi-k3` omits trailing newlines on files it writes. Verification commands that exact-match `\n`-terminated strings fail against it; compare trimmed content.

## Alternatives

- [claude-code-router](https://github.com/musistudio/claude-code-router) routes the API requests behind your session and wins on infrastructure: fallbacks, key rotation, per-request observability, a web UI. It has no concept of specs, lanes, or an architect verifying a diff — the reasoning stays in whatever agent you're sitting in.
- [aider's architect/editor mode](https://aider.chat/docs/usage/modes.html) is the same economic idea, built-in and zero-config, with a proven per-edit cost split. The split lives inside one tool at one API layer — no independent agentic harnesses, no separate verification step, and you leave the Claude Code environment.
- Claude Code's native subagents give per-agent model selection with zero external dependencies, and pitwall builds on them. Alone, they stay within Anthropic models and enforce no spec or verification contract.

Pitwall's trade: cross-vendor agentic harnesses as first-class delegation targets with enforced verification, at the cost of installing and authenticating each lane's CLI — and bringing your own gateway for proxy lanes.

## Docs

- [docs/architecture.md](docs/architecture.md) — the design rationale and invariants
- [docs/lanes.md](docs/lanes.md) — full `lanes.json` schema, per-harness wiring, proxy setup
- [docs/verification.md](docs/verification.md) — install-verification runbook, including the live dispatch test

## Contributing, license, credits

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT — see [LICENSE](LICENSE).

Pitwall began as a fork of [DannyMac180/fable-advisor](https://github.com/DannyMac180/fable-advisor), moving the lane inventory from hardcoded agent files into user config. If you still have the upstream plugin installed, disable it first — both define an agent named `fable-advisor` and a skill named `orchestration`.

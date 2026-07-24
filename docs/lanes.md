# Lane configuration

How to add, remove, or repoint a lane — a named model-harness combination — in `lanes.json`.

## File location

| File | Default path | Override |
|---|---|---|
| Lane config | `~/.claude/pitwall/lanes.json` | `PITWALL_CONFIG` |
| Credentials | `~/.claude/.env` | `PITWALL_ENV_FILE` |

Neither file lives in the plugin repo. On first dispatch, if the config is missing, lane-runner copies `config/lanes.example.json` into place. Put secrets only in the credentials file; preflight and lane-runner load it themselves.

## Schema

Top-level:

| Field | Shape |
|---|---|
| `version` | number; currently `1` |
| `default_lane` | string lane id (routing hint only — never a silent fallback) |
| `lanes` | map of lane-id → lane object |

Per-lane object:

| Field | Required | Meaning |
|---|---|---|
| `harness` | yes | closed enum: `grok` \| `codex` \| `claude` \| `groq` |
| `model` | no | harness model slug; omit to use the harness default |
| `description` | yes | human-readable label for reports |
| `env` | no | map of `{ target_env_var: source_env_var_name }` |
| `extra_flags` | no | array of CLI tokens spliced verbatim into the invocation |
| `capabilities` | yes | `["edit"]` and/or `["suggest-only"]` |
| `timeout_seconds` | no | wall-clock cap in seconds; default `600` |

Source of truth: the schema table in `agents/lane-runner.md` and the shipped example `config/lanes.example.json`.

`suggest-only` marks lanes that return code in a response body but cannot edit files or run verification. No shipped lane uses it — it exists for HTTP-only backends you add yourself (see the `groq` harness below).

### Choosing a model for a lane

Rank candidates on [Artificial Analysis](https://artificialanalysis.ai): the Intelligence Index gives the quality bar, and the cost to run the index gives a $/task proxy. Pick the model with the lowest cost per task that clears the bar for the work you'll route to it. Treat that as the starting order, not the verdict — the harness carries its own token overhead (see the README's cost notes), so confirm with a live dispatch through the lane before relying on it.

### Env indirection

Values in `env` are **env-var names**, not secrets. Example:

```json
"env": {
  "ANTHROPIC_BASE_URL": "ZAI_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY"
}
```

Lane-runner loads the credentials file, reads `$ZAI_BASE_URL` and `$ZAI_API_KEY`, and injects them as `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` for that one subprocess. Secrets never sit in `lanes.json`, so the file is safe to commit.

## Per-harness wiring

### claude

Shim the Anthropic client surface with `env`:

```json
"env": {
  "ANTHROPIC_BASE_URL": "ZAI_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN": "ZAI_API_KEY"
}
```

Direct Anthropic-compat endpoints (z.ai, Moonshot) and the proxy's `/v1/messages` surface both work this way. `claude-native` omits `env` and uses session auth.

### codex

Env shimming does **not** work under ChatGPT-account auth. The CLI ignores `OPENAI_BASE_URL` / `OPENAI_API_KEY` and sends traffic to OpenAI. Route third-party models with `-c model_providers.*` entries in `extra_flags` instead:

```json
"extra_flags": [
  "-c", "model_provider=pwproxy",
  "-c", "model_providers.pwproxy.name=CLIProxyAPI",
  "-c", "model_providers.pwproxy.base_url=http://127.0.0.1:8317/v1",
  "-c", "model_providers.pwproxy.wire_api=responses",
  "-c", "model_providers.pwproxy.env_key=CLIPROXY_API_KEY",
  "-c", "model_providers.pwproxy.stream_idle_timeout_ms=600000",
  "-c", "model_reasoning_effort=medium"
]
```

Rules:

- `base_url` must end in `/v1` — codex appends `/responses`.
- `env_key` is enforced: the named var must exist in the process env (keep it in the lane's `env` map, e.g. `"CLIPROXY_API_KEY": "CLIPROXY_API_KEY"`).
- Always pin `model_reasoning_effort`. Codex defaults unknown models to `xhigh`.

`codex-gpt56` uses native auth and only pins reasoning effort.

### grok

Proxied models are wired **out-of-band** in `~/.grok/config.toml`. Add a `[model.<id>]` block that points at the proxy with `env_key = "CLIPROXY_API_KEY"`. The lane entry only names the model and carries the key:

```json
"model": "glm-5.2",
"env": { "CLIPROXY_API_KEY": "CLIPROXY_API_KEY" }
```

Use `config/grok-config.example.toml` as the template. Native `grok` omits `model` and `env`.

### groq

HTTP chat-completions via `curl` against Groq Inc.'s API. Needs `GROQ_API_KEY`. Lane-runner supports the harness; no shipped lane uses it. Do not confuse with `grok` (xAI's CLI).

## CLIProxyAPI

[CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) is a local gateway at `127.0.0.1:8317`. It re-serves models over `/v1/chat/completions`, `/v1/messages`, and `/v1/responses` at once.

Vendor endpoints often do not speak a harness's wire protocol (`claude` → Anthropic Messages, `codex` → OpenAI Responses, `grok` → xAI). The proxy bridges that mismatch so you can pair any model with any harness.

**Shipped lanes that require the proxy (11 of 16):** every lane except `grok`, `codex-gpt56`, `claude-native`, `glm-cc`, and `kimi-cc`. Those eleven fail at connect time if the proxy is down.

## Required env vars

Put these in `~/.claude/.env` (or the path named by `PITWALL_ENV_FILE`):

| Lanes | Vars |
|---|---|
| `glm-cc` | `ZAI_API_KEY`, `ZAI_BASE_URL` |
| `kimi-cc` | `MOONSHOT_API_KEY`, `MOONSHOT_BASE_URL` |
| `gpt56-cc` | `CLIPROXY_BASE_URL`, `CLIPROXY_API_KEY` |
| All other proxy lanes (`*-grok` / `*-codex` except natives) | `CLIPROXY_API_KEY` |
| `grok`, `codex-gpt56`, `claude-native` | none (native CLI auth) |

`CLIPROXY_BASE_URL` for `gpt56-cc` is the Anthropic-compat base the claude harness hits (typically `http://127.0.0.1:8317`). Codex proxy lanes hardcode the base URL in `extra_flags`; grok proxy lanes read it from `~/.grok/config.toml`.

## Preflight

```bash
~/.claude/plugins/pitwall/scripts/preflight-all.sh
```

Checks: harness binary on `PATH`, and every source env var named in a lane's `env` map is set and non-empty. It does **not** probe `127.0.0.1:8317` or validate `~/.grok/config.toml`. A green preflight can still fail at connect time when the proxy is down or a grok model block is missing.

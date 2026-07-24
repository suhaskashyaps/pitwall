# Verification runbook

Prove a fresh pitwall install works end to end. Check each claim against the filesystem and report any mismatch.

pitwall lives at `~/.claude/plugins/pitwall/`. It turns a Fable 5 session into an orchestrator that dispatches work to configurable lanes (grok, codex, claude harnesses; GLM/Kimi via env shims).

---

## 1. Static checks (no dispatch)

```bash
# 1a. Plugin file inventory
find ~/.claude/plugins/pitwall -type f | sort
```

Expected files:

- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `README.md`, `LICENSE`, `CONTRIBUTING.md`, `.gitignore`
- `agents/fable-advisor.md`
- `agents/lane-runner.md`
- `config/lanes.example.json`
- `config/grok-config.example.toml`
- `docs/architecture.md`, `docs/lanes.md`, `docs/verification.md`
- `scripts/preflight-all.sh`
- `skills/orchestration/SKILL.md`

```bash
# 1b. JSON validity
jq . ~/.claude/plugins/pitwall/.claude-plugin/plugin.json > /dev/null && echo OK
jq . ~/.claude/plugins/pitwall/.claude-plugin/marketplace.json > /dev/null && echo OK
jq . ~/.claude/plugins/pitwall/config/lanes.example.json > /dev/null && echo OK
jq . ~/.claude/pitwall/lanes.json > /dev/null && echo OK
```

Expect four `OK` lines. If `~/.claude/pitwall/lanes.json` is missing, that is the one acceptable failure: first dispatch has not run yet. Copy the example into place:

```bash
mkdir -p ~/.claude/pitwall
cp ~/.claude/plugins/pitwall/config/lanes.example.json ~/.claude/pitwall/lanes.json
```

---

## 2. Preflight matrix

```bash
~/.claude/plugins/pitwall/scripts/preflight-all.sh
```

Expect a table of configured lanes, each row `ok`/`ok`.

If a lane shows `MISSING(VAR)`, the named variable is absent from the credentials file (`~/.claude/.env`). That is correct reporting, not a bug.

Preflight does not check two things: the CLIProxyAPI endpoint itself, and `~/.grok/config.toml`. Cover those with the proxy check below and your own grok config review.

---

## 3. Proxy check for proxy-dependent lanes

Six of the eleven shipped lanes need a local CLIProxyAPI instance:

```bash
curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8317/
```

Expect `200`. Any other code means all six lanes routed through that proxy fail at connect time, not at spec time.

---

## 4. Agent registration

Registration takes effect at session start. In a **new** session:

- Agent list includes `pitwall:lane-runner` and `pitwall:fable-advisor`.
- Skill list includes `pitwall:orchestration`.

If these are absent:

1. The plugin is not in `settings.json`'s `enabledPlugins`. Listing it in `installed_plugins.json` alone is not enough; enable it in settings.
2. The marketplace source type is wrong. Use `directory` (pointing at the plugin root), not `local`. `local` is not a valid source type and is silently rejected. Accepted types include `url`, `github`, `git`, `npm`, `file`, `directory`, and `settings`.

---

## 5. Live dispatch test

In a session where `pitwall:lane-runner` is available, dispatch this exact task to it:

```
LANE: grok

Objective: Create /tmp/pitwall-test/health.py containing a function
health() that returns the string "ok". Trivial task: the point is to
exercise the dispatch loop.

Files: create /tmp/pitwall-test/health.py

Interfaces:
def health() -> str:
    return "ok"

Constraints: one file, one function, work in /tmp/pitwall-test.

Verification: cd /tmp/pitwall-test && python3 -c "from health import health; assert health() == 'ok'; print('PASS')"
```

Expected outcomes:

1. `lane-runner` returns a report headed `LANE REPORT (grok)` with a `MODEL-HARNESS:` line naming the combination it ran, `STATUS: complete`, a `CHANGES:` line for `health.py`, and a `VERIFIED:` line showing the verification command's actual `PASS` output, citing the observed `stopReason`.
2. `/tmp/pitwall-test/health.py` exists, and re-running the verification command by hand prints `PASS`.
3. If grok is unavailable, expect `STATUS: unavailable` with the exact reason, not a fallback where lane-runner writes the file itself. If lane-runner implements the task directly, that is a critical defect: report it.

---

## Gotchas

These reflect observed behavior of specific harness versions. Re-verify against yours.

- **`env` shimming does not work on the `codex` harness under ChatGPT-account auth.** It ignores `OPENAI_BASE_URL` / `OPENAI_API_KEY` and sends everything to OpenAI regardless. Use `-c model_providers.*` flags in `extra_flags` instead.
- **Direct vendor endpoints cannot serve the `codex` harness.** Codex speaks only the Responses API, and direct vendor endpoints often 404 on `/responses`. Route codex pairings against third-party models through a local proxy that implements the Responses API.
- **Pin `model_reasoning_effort` on codex lanes.** Codex defaults models it does not recognize to `xhigh` reasoning effort, which burns more tokens than needed. Pin the effort level (e.g. `medium`) in `extra_flags` for those pairings.
- **Without a `timeout`/`gtimeout` binary, lane runs are uncapped.** A hung harness blocks the caller indefinitely. `brew install coreutils` installs `gtimeout` and fixes this.

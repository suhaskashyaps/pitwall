# Contributing

How to fix a bug, add a lane, or add a harness in pitwall.

## Dev setup

1. Clone this repo to `~/.claude/plugins/pitwall`.
2. Register it as a directory-source marketplace in `~/.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "pitwall": {
      "source": {
        "source": "directory",
        "path": "~/.claude/plugins/pitwall"
      }
    }
  },
  "enabledPlugins": {
    "pitwall@pitwall": true
  }
}
```

Merge those keys into your existing settings; do not replace the whole file. Write `path` as an absolute path (`/home/you/...`, not `~`): the registered value is stored expanded.

3. Restart Claude Code, or run `/reload-plugins`.
4. Confirm `pitwall:lane-runner` and `pitwall:fable-advisor` appear in the agent list.

## Running the checks

From the repo root:

```bash
bash -n scripts/preflight-all.sh
jq . .claude-plugin/plugin.json
jq . .claude-plugin/marketplace.json
jq . config/lanes.example.json
scripts/preflight-all.sh
```

`preflight-all.sh` reads your own lane config at `~/.claude/pitwall/lanes.json`. Seed it if missing:

```bash
mkdir -p ~/.claude/pitwall
cp config/lanes.example.json ~/.claude/pitwall/lanes.json
```

Then run the live dispatch test in `docs/verification.md`.

## Adding a lane (config only)

1. Edit `~/.claude/pitwall/lanes.json`. Add a lane object under `lanes` with `harness`, `description`, `capabilities`, and any of `model`, `env`, `extra_flags`, `timeout_seconds`.
2. `env` values are source variable **names**, not secrets.
3. Run `scripts/preflight-all.sh` and confirm the new row is ready.
4. Run one live write-and-verify dispatch through the new lane before you rely on it.
5. If the lane is generally useful, mirror it into `config/lanes.example.json` and add a row to the README lane table in the same PR.

## Adding a harness (code change)

A new model on an existing harness is config only. A new harness is a code change.

1. Edit `agents/lane-runner.md`.
2. Add the invocation template for the new harness.
3. Add the preflight rule (binary on PATH, required env sources).
4. Add the failure gate (when to return `STATUS: unavailable`).
5. Never special-case a lane id in agent logic. Drive behavior from JSON fields only.
6. Update `docs/lanes.md` with the new harness's wiring rules.

## What a good PR looks like

- One concern per PR.
- Back every behavior claim with a command you ran and its output.
- Update `config/lanes.example.json` and docs in the same PR as the change.
- Put no secrets in the repo. `env` values in `lanes.json` are variable names. Credentials stay in `~/.claude/.env` (or `$PITWALL_ENV_FILE`) and never enter the tree.

## License

Contributions are MIT-licensed. See `LICENSE`.

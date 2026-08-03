# Goal: cost and trace attribution in local Langfuse

Attribute the cost and full trace of any task to a local Langfuse instance, whether the task runs through the pitwall fleet or as a plain Claude Code session, and compare the two modes head to head.

## Decisions (locked with user, 2026-07-25)

1. **Langfuse**: self-hosted via docker compose, fully local. No cloud.
2. **Capture**: hybrid. Session-level telemetry from Claude Code where available; per-dispatch usage parsed from each harness's JSON output and posted by a reporter script. Covers every lane regardless of auth path (native CLI auth or CLIProxyAPI).
3. **Cost basis**: token counts recorded everywhere; dollar cost computed from a maintained per-model price table and flagged `imputed`. Real billed cost recorded where an actual API bill exists.
4. **Comparison**: explicit A/B pairing. A wrapper runs the same task twice, once solo and once through pitwall, under one experiment ID, and emits a side-by-side report.

## Constraints

- All work lives on branch `langfuse-attribution` of this repo. Local commits only. Never push. Never merge to main.
- Every dispatched lane runs at high reasoning effort where the harness exposes the setting.
- Secrets (Langfuse keys) go in `~/.claude/.env`, never in the repo.
- The architect writes no implementation code; every phase below routes through a lane with a five-part spec.

## Components

| Component | Path | Purpose |
|---|---|---|
| Langfuse stack | `observability/langfuse/docker-compose.yml` | Local Langfuse v3 (web, worker, postgres, clickhouse, redis, minio) |
| Price table | `config/prices.json` | $/Mtok input, output, cache per model ID; source of imputed cost |
| Reporter | `scripts/pitwall_trace.py` | Langfuse Python SDK client. Subcommands: `ingest-lane` (harness JSON on stdin plus lane metadata), `ingest-session` (Claude Code session JSONL), `report <experiment-id>` (side-by-side comparison) |
| Lane hook | `agents/lane-runner.md` | Post-dispatch step: pipe harness usage JSON to the reporter with `{experiment_id, mode: pitwall, lane, model_harness}` |
| A/B wrapper | `scripts/ab-run` | Generates experiment ID, runs solo leg headless, runs pitwall leg, invokes `report` |

Trace shape: one Langfuse trace per leg. The pitwall leg holds one span per lane dispatch (tokens, imputed cost, lane, model-harness). The solo leg holds the session usage. Both carry the experiment ID in metadata.

**Capture is deterministic, never LLM-remembered** (fable-advisor reshape, 2026-07-25). The lane-runner does not decide to report; the harness command line itself tees raw JSON output into a run directory (`~/.claude/pitwall/runs/<experiment-id>/<lane>.json`), keyed by `PITWALL_EXPERIMENT_ID` exported by `ab-run`. `pitwall_trace.py ingest-lane` sweeps the directory after the leg completes, so a missing file is a loud ingest error, not a silently missing span that biases the A/B comparison. Consequence for Phase 4: the invocation templates in `agents/lane-runner.md` change to usage-emitting output modes (`codex exec --json` instead of `--output-last-message`; `claude -p --output-format json` instead of `text`), and the final-message extraction that feeds `HARNESS SAID` adapts to the new output shape. The env var also replaces prompt-hop threading of the experiment ID from architect to lane-runner.

## Phases

| # | Phase | Route | Effort |
|---|---|---|---|
| 0 | Branch + this doc | architect (trivial) | done |
| 1 | Research: harness usage formats, Langfuse compose, Claude Code telemetry | cheap read-only agents, parallel | n/a |
| 2 | Langfuse infra up, keys in `~/.claude/.env`, health verified | codex-gpt56 | high |
| 3 | Price table + reporter with unit fixtures for all three harness formats | race: codex-gpt56 vs kimi-cc, architect picks stronger diff | high |
| 4 | Lane-runner template change: usage-emitting output modes + deterministic tee to run directory | codex-gpt56 | high |
| 5 | A/B wrapper + report command | grok | high |
| 6 | End-to-end demo: one sample task both ways, verify paired traces and cost comparison in Langfuse | architect verifies | n/a |

Phase 3 is raced because usage-format parsing across three harnesses is the correctness core; a silent parsing bug corrupts every downstream number.

## Verification

- `docker compose ps` shows all Langfuse services healthy; API answers on localhost.
- Reporter unit run: fixtures for `claude -p --output-format json`, `codex exec --json`, and grok CLI output each produce a trace with correct token counts and imputed cost.
- End-to-end: `ab-run` on a sample task yields two traces sharing one experiment ID in Langfuse, and `report` prints the side-by-side comparison with per-lane spans on the pitwall leg.

## Research findings (Phase 1, settled 2026-07-25)

- Session JSONL transcripts record placeholder token counts (known Claude Code issue; input undercounts 100x+). The solo leg therefore uses `claude -p --output-format json`, which carries accurate exclusive usage buckets plus real `total_cost_usd`. JSONL ingestion is out of scope.
- Grok's `--output-format json` (already the lane-runner template) reports `usage`, per-model `modelUsage`, and real `total_cost_usd`. Grok lanes need no template change for usage, only the tee.
- Codex usage arrives only in the `--json` JSONL event stream (`token_count` events). `--json` coexists with `--output-last-message`, so `HARNESS SAID` extraction is unchanged; the tee captures stdout JSONL.
- Langfuse: official compose file is the base; headless org/project/key provisioning via `LANGFUSE_INIT_*`; OTLP endpoint accepts traces only (http/protobuf). Reporter posts `cost_details` directly (rendered verbatim, no model-definition matching). Query by tags (AND semantics): tag each trace with `exp-<id>` plus `mode:<pitwall|solo>`.
- Claude Code can additionally stream OTel traces to Langfuse's OTLP endpoint (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`, http/protobuf). Optional live view only; authoritative numbers ride the JSON path.
- This machine had no container runtime; Phase 2 installs colima + docker CLI via Homebrew.

## Outcome (Phase 6, 2026-07-25)

End-to-end demo `exp-demo-slugify-1` ran one real task (slugify + tests) both ways in isolated copies. Langfuse holds the paired traces: pitwall leg $1.293 (architect claude-fable-5 $0.906 + claude-sonnet-5 subagent $0.332 + grok-4.5-build lane $0.055) vs solo leg $1.073, ratio 1.21. The deterministic tee fired inside a real headless architect session; a live defect (multi-model claude sessions broke the parser) was found by the loud-failure design, fixed, and regression-tested (7 tests). Final advisor check passed after one fix: grok stderr now goes to `<lane>.stderr.log` instead of contaminating the usage capture.

Documented rough edges, accepted as-is:
- Ingest is not idempotent: re-running `--ingest-only` for the same experiment posts duplicate traces, and the report then picks whichever trace the API returns first. Use a fresh experiment ID after partial failures.
- Experiment tags double-prefix when the ID already starts with `exp-` (tag `exp-exp-...`). Self-consistent between tagging and query; cosmetic.
- The report's lane table shows one row per generation, so a multi-model architect prints two `architect` rows distinguished only by the trace, not a model column.
- The 1.21 cost ratio is one trivial task; orchestration overhead dominates small tasks and the number generalizes to nothing.

## Risks

- Two lanes pin `model_reasoning_effort=medium` in `lanes.json` (glm-codex, grok45-codex); if routed, the dispatch overrides to high for this work.
- Price-table numbers are seeded by the implementing lane as `verified: false`; the architect audits them against published pricing before the demo (imputed costs are only as good as the table).

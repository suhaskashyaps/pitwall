#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["langfuse"]
# ///
"""Compare many single-lane experiments against one baseline.

`pitwall_trace.py report` compares the two legs INSIDE one experiment. A lane
sweep is the other shape: N experiments of one leg each, plus a baseline, which
that report cannot express. This joins them.

Cost comes from the ingested traces. Wall clock comes from each leg's
leg-start.txt / leg-end.txt markers, never from harness-reported duration_ms.
Gates are re-run here rather than trusted from any leg's own report, because a
failed leg is cheap and its report will still read as success.

Usage:
  pitwall_compare.py "<label>=<experiment-id>=<solo|lane>" ...

  pitwall_compare.py \\
    "baseline=my-solo-run=solo" \\
    "glm-codex=my-glm-codex-run=lane" \\
    "grok=my-grok-run=lane"

Options:
  --verify "<cmd>"  acceptance command to re-run in each leg's work tree
                    (default: none, gates column reports "not checked")
  --json <path>     also write the rows as JSON
"""

import argparse
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Runs live outside ~/.claude by default (that prefix is a protected path and
# harness writes there get denied); older experiments may still be under it.
RUN_ROOTS = [
    Path(p).expanduser()
    for p in (
        __import__("os").environ.get("PITWALL_RUNS_ROOT", ""),
        "~/.local/share/pitwall/runs",
        "~/.claude/pitwall/runs",
    )
    if p
]

spec = importlib.util.spec_from_file_location("pitwall_trace", HERE / "pitwall_trace.py")
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


def find_run_dir(experiment: str) -> Path:
    for root in RUN_ROOTS:
        if (root / experiment).is_dir():
            return root / experiment
    return RUN_ROOTS[0] / experiment


def wall_clock(run_dir: Path, leg: str) -> str:
    start_f, end_f = run_dir / leg / "leg-start.txt", run_dir / leg / "leg-end.txt"
    if not (start_f.exists() and end_f.exists()):
        return "n/a"
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    try:
        start = datetime.strptime(start_f.read_text().strip(), fmt)
        end = datetime.strptime(end_f.read_text().strip(), fmt)
    except ValueError:
        return "n/a"
    total = int((end - start).total_seconds())
    return f"{total // 60}m{total % 60:02d}s"


def gates(work_dir: Path, verify: str | None) -> str:
    """Re-run the acceptance command. A leg's own report is not evidence."""
    if not verify:
        return "not checked"
    if not work_dir.is_dir():
        return "no work tree"
    try:
        done = subprocess.run(
            ["bash", "-e", "-o", "pipefail", "-c", verify],
            cwd=work_dir, capture_output=True, timeout=600,
        )
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    return "pass" if done.returncode == 0 else f"FAIL (exit {done.returncode})"


def leg_costs(experiment: str, trace_name: str, config) -> dict | None:
    payload = trace.api_get("/api/public/traces", {"tags": f"exp-{experiment}"}, config)
    rows = trace.response_rows(payload, "/api/public/traces")
    found = trace.optional_trace(rows, trace_name)
    if found is None:
        return None
    obs = [
        o for o in trace.fetch_observations(found, config)
        if o.get("type") == "GENERATION"
    ]
    by_lane: dict[str, float] = {}
    for o in obs:
        md = o.get("metadata") if isinstance(o.get("metadata"), dict) else {}
        lane = md.get("lane", o.get("name", "?"))
        by_lane[lane] = by_lane.get(lane, 0.0) + trace.observation_totals([o])["cost"]
    totals = trace.observation_totals(obs)
    meta = found.get("metadata") or {}
    return {
        "total": totals["cost"],
        "by_lane": by_lane,
        "skipped": meta.get("skipped_captures", []),
        "missing": meta.get("missing_captures", []),
        "tokens": {k: totals[k] for k in ("input", "cache_read", "cache_write", "output")},
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compare single-lane experiments against a baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("legs", nargs="+", metavar="label=experiment=solo|lane")
    ap.add_argument("--verify", help="acceptance command re-run in each work tree")
    ap.add_argument("--json", dest="json_out", type=Path)
    args = ap.parse_args(argv)

    config = trace.langfuse_config()
    rows = []
    for arg in args.legs:
        try:
            label, experiment, mode = arg.split("=", 2)
        except ValueError:
            print(f"error: expected label=experiment=solo|lane, got {arg!r}", file=sys.stderr)
            return 2
        if mode not in {"solo", "lane"}:
            print(f"error: mode must be solo or lane, got {mode!r}", file=sys.stderr)
            return 2
        # a corrected re-ingest may carry a tag suffix the run dir does not have
        run_dir = find_run_dir(experiment.removesuffix("-fix"))
        leg = "solo" if mode == "solo" else "pitwall"
        data = leg_costs(experiment, f"{leg}-leg", config)
        if data is None:
            rows.append({"label": label, "experiment": experiment, "absent": True})
            continue
        architect = 0.0 if mode == "solo" else data["by_lane"].get("architect", 0.0)
        rows.append({
            "label": label, "experiment": experiment, "mode": mode,
            "total": data["total"],
            "architect": architect,
            "lane": 0.0 if mode == "solo" else data["total"] - architect,
            "wall": wall_clock(run_dir, leg),
            "gates": gates(run_dir / f"work-{leg}", args.verify),
            "skipped": data["skipped"], "missing": data["missing"],
        })

    print("| leg | total $ | architect $ | lane $ | wall clock | gates | capture problems |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        if r.get("absent"):
            print(f"| {r['label']} | NOT INGESTED | | | | | |")
            continue
        problems = ", ".join(r["skipped"] + r["missing"]) or "none"
        arch = "n/a" if r["mode"] == "solo" else f"{r['architect']:.6f}"
        lane = "n/a" if r["mode"] == "solo" else f"{r['lane']:.6f}"
        print(f"| {r['label']} | {r['total']:.6f} | {arch} | {lane} | "
              f"{r['wall']} | {r['gates']} | {problems} |")

    base = next(
        (r for r in rows if r.get("mode") == "solo" and not r.get("absent")), None
    )
    if base and base["total"]:
        print(f"\nBaseline: ${base['total']:.6f}\n")
        print("| leg | total/baseline | lane-only/baseline |")
        print("|---|---|---|")
        for r in rows:
            if r.get("absent") or r["mode"] == "solo":
                continue
            print(f"| {r['label']} | {r['total'] / base['total']:.3f}x | "
                  f"{r['lane'] / base['total']:.3f}x |")
    else:
        print("\nNo baseline leg given, so no ratios. Pass one as label=experiment=solo.")

    if any(r.get("skipped") or r.get("missing") for r in rows):
        print("\nSome legs had capture problems; their cost is under-reported. "
              "See the capture problems column.", file=sys.stderr)

    if args.json_out:
        args.json_out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nRaw: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

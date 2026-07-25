#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "langfuse>=3,<4",
# ]
# ///
"""Attribute pitwall and solo harness usage to Langfuse traces."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PRICES_FILE = ROOT / "config" / "prices.json"
LANES_FILE = Path.home() / ".claude" / "pitwall" / "lanes.json"
BUCKETS = ("input", "cache_read", "cache_write", "output")


class PitwallError(Exception):
    """A user-facing ingestion or reporting error."""


class AlreadyIngestedError(PitwallError):
    """This leg is already in Langfuse. Re-posting would double-count its cost.

    Exits 3 rather than 2 so a wrapper can tell "already done, carry on" from a
    genuine ingest failure.
    """


class UnusableCaptureError(PitwallError):
    """A capture that carries no interpretable usage at all.

    Raised ONLY for a dispatch that died before writing anything (empty or
    syntactically broken file). Never for a capture we can read but fail to
    price or attribute: those carry real spend, and skipping them would
    under-report the leg, which is the exact failure this module exists to
    prevent. Semantic problems must stay fatal.
    """


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PitwallError(f"{path}: cannot read: {exc}") from exc
    if not raw.strip():
        raise UnusableCaptureError(f"{path}: file is empty (dispatch wrote nothing)")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UnusableCaptureError(f"{path}: cannot parse JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise PitwallError(f"{path}: expected a JSON object")
    return value


def integer(value: Any, field: str, path: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PitwallError(f"{path}: field {field} must be numeric")
    result = int(value)
    if result < 0 or result != value:
        raise PitwallError(f"{path}: field {field} must be a non-negative integer")
    return result


def number(value: Any, field: str, path: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PitwallError(f"{path}: field {field} must be numeric")
    result = float(value)
    if result < 0:
        raise PitwallError(f"{path}: field {field} must be non-negative")
    return result


def usage_value(usage: dict[str, Any], key: str, path: Path) -> int:
    return integer(usage.get(key, 0), f"usage.{key}", path)


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return values
    except OSError as exc:
        raise PitwallError(f"{path}: cannot read environment file: {exc}") from exc
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def langfuse_config() -> dict[str, str]:
    fallback = parse_env_file(Path.home() / ".claude" / ".env")
    names = ("LANGFUSE_HOST", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    config = {name: os.environ.get(name) or fallback.get(name, "") for name in names}
    missing = [name for name, value in config.items() if not value]
    if missing:
        raise PitwallError("missing Langfuse configuration: " + ", ".join(missing))
    return config


def load_prices(path: Path = PRICES_FILE) -> dict[str, dict[str, Any]]:
    data = read_json(path)
    models = data.get("models")
    if not isinstance(models, dict):
        raise PitwallError(f"{path}: missing models price table")
    return models


def impute_cost(
    model: str,
    usage_details: dict[str, int],
    prices: dict[str, dict[str, Any]],
) -> float:
    if model not in prices:
        raise PitwallError(f"missing price for model {model}")
    price = prices[model]
    price_keys = {
        "input": "input_per_mtok",
        "cache_read": "cache_read_per_mtok",
        "cache_write": "cache_write_per_mtok",
        "output": "output_per_mtok",
    }
    total = 0.0
    for bucket, price_key in price_keys.items():
        value = price.get(price_key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PitwallError(f"missing price {price_key} for model {model}")
        total += usage_details[bucket] / 1_000_000 * float(value)
    return total


def parse_grok(
    path: Path,
    data: dict[str, Any],
    prices: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    usage = data.get("usage")
    model_usage = data.get("modelUsage")
    if not isinstance(usage, dict):
        raise PitwallError(f"{path}: grok result is missing usage")
    if not isinstance(model_usage, dict) or not model_usage:
        raise PitwallError(f"{path}: grok result is missing modelUsage")
    if len(model_usage) != 1:
        models = ", ".join(sorted(str(key) for key in model_usage))
        raise PitwallError(f"{path}: expected one grok model, found: {models}")
    model = str(next(iter(model_usage)))
    raw_input = usage_value(usage, "input_tokens", path)
    cache_read = usage_value(usage, "cache_read_input_tokens", path)
    # Grok normally reports input_tokens inclusive of cache reads. A cache count
    # larger than input indicates an already-exclusive input counter.
    # Cache writes are billed at a premium by several providers, so a hardcoded
    # zero silently under-charges every imputed proxy lane.
    # Harnesses spell this differently; take the larger rather than the first, so
    # a capture carrying both under different names cannot under-report.
    cache_write = max(
        usage_value(usage, "cache_creation_input_tokens", path),
        usage_value(usage, "cache_write_input_tokens", path),
    )
    input_exclusive = raw_input if cache_read > raw_input else raw_input - cache_read
    if cache_write and cache_write <= input_exclusive:
        input_exclusive -= cache_write
    usage_details = {
        "input": max(0, input_exclusive),
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": usage_value(usage, "output_tokens", path),
    }
    # Native xAI grok reports total_cost_usd. Models routed through the local
    # CLIProxyAPI do not: the proxy knows no pricing, so the field is absent.
    # Impute from the price table rather than dropping the dispatch, which
    # would silently under-report every proxy-routed lane's cost to zero.
    # A proxy may omit the field entirely OR emit it as a zero placeholder.
    # Treating a zero as authoritative would report a lane that plainly burned
    # tokens as free, so impute whenever there is usage but no positive cost.
    # A capture with no usage at all has nothing to price: imputing would only
    # raise a spurious "missing price" for a dispatch that spent nothing.
    raw_cost = data.get("total_cost_usd")
    has_usage = any(usage_details[bucket] for bucket in usage_details)
    harness_cost = None if raw_cost is None else number(raw_cost, "total_cost_usd", path)
    if harness_cost:
        cost, cost_source = harness_cost, "harness"
    elif has_usage:
        cost, cost_source = impute_cost(model, usage_details, prices), "imputed"
    else:
        # No usage and no positive cost: a dispatch that spent nothing.
        cost, cost_source = 0.0, "harness"
    return {
        "model": model,
        "usage_details": usage_details,
        "cost_details": {"total": cost},
        "model_harness": "grok",
        "cost_source": cost_source,
        "harness_metadata": {
            "reasoning_tokens": usage_value(usage, "reasoning_tokens", path),
            "total_tokens": usage_value(usage, "total_tokens", path),
            "num_turns": integer(data.get("num_turns", 0), "num_turns", path),
            "stop_reason": data.get("stopReason"),
        },
    }


def parse_codex(
    path: Path,
    model: str,
    prices: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    last_usage: dict[str, Any] | None = None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PitwallError(f"{path}: cannot read JSONL: {exc}") from exc
    # A codex dispatch that died before emitting anything leaves an empty file.
    # That is a dead dispatch, not a corrupt receipt: it must be skippable like
    # any other, or one crashed lane takes the whole leg's cost down with it.
    if not raw.strip():
        raise UnusableCaptureError(f"{path}: file is empty (dispatch wrote nothing)")
    lines = raw.splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PitwallError(f"{path}:{line_number}: cannot parse JSONL: {exc}") from exc
        if not isinstance(event, dict):
            raise PitwallError(f"{path}:{line_number}: expected a JSON object")
        payload = event.get("payload")
        if (
            event.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "token_count"
        ):
            info = payload.get("info")
            candidate = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(candidate, dict):
                raise PitwallError(
                    f"{path}:{line_number}: token_count is missing "
                    "payload.info.total_token_usage"
                )
            last_usage = candidate
        elif event.get("type") == "turn.completed":
            candidate = event.get("usage")
            if not isinstance(candidate, dict):
                raise PitwallError(
                    f"{path}:{line_number}: turn.completed is missing usage"
                )
            last_usage = candidate
    if last_usage is None:
        raise PitwallError(
            f"{path}: no event_msg/token_count or turn.completed usage record found"
        )
    raw_input = usage_value(last_usage, "input_tokens", path)
    cache_read = usage_value(last_usage, "cached_input_tokens", path)
    if cache_read > raw_input:
        raise PitwallError(f"{path}: cached_input_tokens exceeds input_tokens")
    usage_details = {
        "input": raw_input - cache_read,
        "cache_read": cache_read,
        "cache_write": usage_value(last_usage, "cache_write_input_tokens", path),
        "output": usage_value(last_usage, "output_tokens", path),
    }
    return {
        "model": model,
        "usage_details": usage_details,
        "cost_details": {"total": impute_cost(model, usage_details, prices)},
        "model_harness": "codex",
        "cost_source": "imputed",
        "harness_metadata": {
            "reasoning_output_tokens": usage_value(
                last_usage, "reasoning_output_tokens", path
            ),
            # turn.completed usage carries no total_tokens; derive it
            "total_tokens": integer(
                last_usage.get("total_tokens", raw_input + usage_details["output"]),
                "usage.total_tokens",
                path,
            ),
        },
    }


def parse_claude(
    path: Path,
    data: dict[str, Any],
    fallback_model: str | None,
    name: str,
) -> list[dict[str, Any]]:
    model = data.get("model")
    model_usage = data.get("modelUsage")
    if not (isinstance(model, str) and model):
        if isinstance(model_usage, dict) and model_usage:
            generations = []
            for model_id, raw_usage in model_usage.items():
                model_id = str(model_id)
                if not isinstance(raw_usage, dict):
                    raise PitwallError(
                        f"{path}: modelUsage.{model_id} must be an object"
                    )
                usage_details = {
                    "input": integer(
                        raw_usage.get("inputTokens", 0),
                        f"modelUsage.{model_id}.inputTokens",
                        path,
                    ),
                    "cache_read": integer(
                        raw_usage.get("cacheReadInputTokens", 0),
                        f"modelUsage.{model_id}.cacheReadInputTokens",
                        path,
                    ),
                    "cache_write": integer(
                        raw_usage.get("cacheCreationInputTokens", 0),
                        f"modelUsage.{model_id}.cacheCreationInputTokens",
                        path,
                    ),
                    "output": integer(
                        raw_usage.get("outputTokens", 0),
                        f"modelUsage.{model_id}.outputTokens",
                        path,
                    ),
                }
                cost = number(
                    raw_usage.get("costUSD"),
                    f"modelUsage.{model_id}.costUSD",
                    path,
                )
                generations.append(
                    {
                        "name": f"{name}:{model_id}",
                        "model": model_id,
                        "usage_details": usage_details,
                        "cost_details": {"total": cost},
                        "model_harness": "claude",
                        "cost_source": "harness",
                        "harness_metadata": {},
                    }
                )
            return generations
        model = fallback_model
    if not model:
        raise PitwallError(
            f"{path}: claude result has no model; supply --model or lane metadata"
        )
    usage = data.get("usage")
    if not isinstance(usage, dict):
        raise PitwallError(f"{path}: claude result is missing usage")
    usage_details = {
        # Anthropic reports these four input/cache buckets as already exclusive.
        "input": usage_value(usage, "input_tokens", path),
        "cache_read": usage_value(usage, "cache_read_input_tokens", path),
        "cache_write": usage_value(usage, "cache_creation_input_tokens", path),
        "output": usage_value(usage, "output_tokens", path),
    }
    cost = number(data.get("total_cost_usd"), "total_cost_usd", path)
    return [
        {
            "name": name,
            "model": model,
            "usage_details": usage_details,
            "cost_details": {"total": cost},
            "model_harness": "claude",
            "cost_source": "harness",
            "harness_metadata": {},
        }
    ]


def read_lane_config(path: Path = LANES_FILE) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = read_json(path)
    raw_lanes = data.get("lanes", data)
    result: dict[str, dict[str, Any]] = {}
    if isinstance(raw_lanes, dict):
        for name, value in raw_lanes.items():
            if isinstance(value, dict):
                result[str(name)] = value
    elif isinstance(raw_lanes, list):
        for value in raw_lanes:
            if isinstance(value, dict) and isinstance(value.get("name"), str):
                result[value["name"]] = value
    return result


def sidecar_metadata(
    path: Path,
    lane_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sidecar = path.with_name(f"{path.stem}.meta.json")
    if sidecar.exists():
        data = read_json(sidecar)
        return {
            key: data[key]
            for key in ("lane", "model", "harness")
            if isinstance(data.get(key), str) and data[key]
        }
    lane = path.stem
    aliases = (lane, lane.removesuffix("-lane"))
    configured: dict[str, Any] = {}
    for alias in aliases:
        if alias in lane_config:
            configured = lane_config[alias]
            break
    metadata: dict[str, Any] = {"lane": lane}
    for key in ("model", "harness"):
        if isinstance(configured.get(key), str) and configured[key]:
            metadata[key] = configured[key]
    return metadata


def default_model(harness: str) -> str | None:
    return {
        "grok": "grok-code-fast",
        "codex": "gpt-5.6-sol",
    }.get(harness)


def parse_lane_file(
    path: Path,
    metadata: dict[str, Any],
    prices: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    name = str(metadata.get("lane", path.stem))
    if path.suffix == ".jsonl":
        harness = "codex"
        model = metadata.get("model") or default_model(harness)
        if not model:
            raise PitwallError(f"{path}: cannot resolve model for lane")
        parsed_generations = [parse_codex(path, str(model), prices)]
    elif path.suffix == ".json":
        data = read_json(path)
        if "stopReason" in data:
            harness = "grok"
            parsed_generations = [parse_grok(path, data, prices)]
        elif "total_cost_usd" in data and "usage" in data:
            harness = "claude"
            parsed_generations = parse_claude(
                path, data, metadata.get("model"), name
            )
        else:
            raise PitwallError(f"{path}: unrecognized lane result format")
    else:
        raise PitwallError(f"{path}: unsupported lane result extension")
    configured_harness = metadata.get("harness")
    if configured_harness and configured_harness != harness:
        raise PitwallError(
            f"{path}: sidecar harness {configured_harness!r} "
            f"does not match detected {harness!r}"
        )
    for parsed in parsed_generations:
        parsed.setdefault("name", name)
        parsed["metadata"] = {
            "lane": metadata.get("lane", path.stem),
            "model_harness": harness,
            "cost_source": parsed.pop("cost_source"),
            **parsed.pop("harness_metadata"),
        }
    return parsed_generations


def lane_result_files(run_dir: Path) -> list[Path]:
    if not run_dir.is_dir():
        raise PitwallError(f"{run_dir}: run directory does not exist")
    files = [
        path
        for path in sorted(run_dir.iterdir())
        if path.is_file()
        and path.suffix in {".json", ".jsonl"}
        and not path.name.endswith(".meta.json")
        and path.name != "solo.json"
    ]
    if not files:
        raise PitwallError(f"{run_dir}: no lane result files found")
    return files


def missing_dispatch_captures(run_dir: Path) -> list[str]:
    """Sidecars are written when a dispatch STARTS; captures when it produces usage.

    A sidecar with no sibling capture means a dispatch ran whose cost is absent
    from the receipt -- the work may well have landed (S7: a dispatch wrote its
    capture outside the experiment dir, hiding $0.47 behind a passing gate).
    Report those rather than letting the leg under-report silently.
    """
    missing = []
    for sidecar in sorted(run_dir.glob("*.meta.json")):
        stem = sidecar.name[: -len(".meta.json")]
        if not stem:
            continue
        if not any((run_dir / f"{stem}{ext}").is_file() for ext in (".json", ".jsonl")):
            missing.append(stem)
    return missing


def build_lane_trace(
    run_dir: Path,
    experiment: str,
    prices_path: Path = PRICES_FILE,
    lanes_path: Path = LANES_FILE,
) -> dict[str, Any]:
    prices = load_prices(prices_path)
    lane_config = read_lane_config(lanes_path)
    generations = []
    skipped: list[str] = []
    missing = missing_dispatch_captures(run_dir)
    for path in lane_result_files(run_dir):
        # A dispatch that died before the harness wrote usage leaves a zero-byte
        # or truncated capture. That is a dead dispatch with no cost to attribute,
        # so it must not abort ingest for the sibling captures that did land.
        # Only UnusableCaptureError is skipped: an unpriced model or a corrupt
        # sidecar is a capture with REAL spend behind it and stays fatal.
        # Sidecar resolution stays OUTSIDE the skip: a corrupt sidecar describes
        # a capture that DID land, so dropping it would discard real spend.
        metadata = sidecar_metadata(path, lane_config)
        try:
            generations.extend(parse_lane_file(path, metadata, prices))
        except UnusableCaptureError as exc:
            skipped.append(path.name)
            print(f"warning: skipping unusable capture {exc}", file=sys.stderr)
    if not generations:
        detail = f"{len(skipped)} skipped: {', '.join(skipped)}" if skipped else "none parsed"
        if missing:
            detail += f"; {len(missing)} dispatch(es) left no capture: {', '.join(missing)}"
        raise PitwallError(f"{run_dir}: every lane capture was unusable ({detail})")
    if skipped:
        print(
            f"warning: ingested {len(generations)} generation(s); "
            f"skipped {len(skipped)} unusable capture(s): {', '.join(skipped)}",
            file=sys.stderr,
        )
    if missing:
        print(
            f"warning: {len(missing)} dispatch(es) have a sidecar but no capture, "
            f"so their cost is MISSING from this leg: {', '.join(missing)}",
            file=sys.stderr,
        )
    return {
        "name": "pitwall-leg",
        "tags": [f"exp-{experiment}", "mode:pitwall"],
        "metadata": {
            "experiment_id": experiment,
            "mode": "pitwall",
            "skipped_captures": skipped,
            "missing_captures": missing,
        },
        "generations": generations,
    }


def build_solo_trace(
    json_file: Path,
    experiment: str,
    fallback_model: str | None,
) -> dict[str, Any]:
    data = read_json(json_file)
    generations = parse_claude(json_file, data, fallback_model, "solo")
    for generation in generations:
        generation["metadata"] = {
            "lane": "solo",
            "model_harness": "claude",
            "cost_source": generation.pop("cost_source"),
            **generation.pop("harness_metadata"),
        }
    return {
        "name": "solo-leg",
        "tags": [f"exp-{experiment}", "mode:solo"],
        "metadata": {"experiment_id": experiment, "mode": "solo"},
        "generations": generations,
    }


def post_trace(trace: dict[str, Any]) -> None:
    config = langfuse_config()
    try:
        from langfuse import Langfuse
    except ImportError as exc:
        raise PitwallError("langfuse is not installed; run this script with uv") from exc
    client = Langfuse(
        public_key=config["LANGFUSE_PUBLIC_KEY"],
        secret_key=config["LANGFUSE_SECRET_KEY"],
        base_url=config["LANGFUSE_HOST"],
    )
    trace_id = client.create_trace_id()
    root = client.start_span(
        trace_context={"trace_id": trace_id},
        name=trace["name"],
        metadata=trace["metadata"],
    )
    root.update_trace(
        name=trace["name"],
        tags=trace["tags"],
        metadata=trace["metadata"],
    )
    for item in trace["generations"]:
        generation = root.start_observation(
            name=item["name"],
            as_type="generation",
            model=item["model"],
            usage_details=item["usage_details"],
            cost_details=item["cost_details"],
            metadata=item["metadata"],
        )
        generation.end()
    root.end()
    client.flush()


def api_get(path: str, query: dict[str, str], config: dict[str, str]) -> dict[str, Any]:
    host = config["LANGFUSE_HOST"].rstrip("/")
    url = f"{host}{path}?{urllib.parse.urlencode(query)}"
    credentials = (
        f"{config['LANGFUSE_PUBLIC_KEY']}:{config['LANGFUSE_SECRET_KEY']}".encode()
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": "Basic " + base64.b64encode(credentials).decode()},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise PitwallError(f"Langfuse API request failed for {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PitwallError(f"Langfuse API returned invalid data for {path}")
    return payload


def response_rows(payload: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        raise PitwallError(f"Langfuse API response for {endpoint} has no data list")
    return [row for row in rows if isinstance(row, dict)]


def observation_totals(observations: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {bucket: 0 for bucket in BUCKETS}
    totals["cost"] = 0.0
    for observation in observations:
        usage = observation.get("usageDetails") or observation.get("usage_details") or {}
        costs = observation.get("costDetails") or observation.get("cost_details") or {}
        if isinstance(usage, dict):
            for bucket in BUCKETS:
                totals[bucket] += int(usage.get(bucket, 0) or 0)
        if costs:
            totals["cost"] += float(costs.get("total", 0) or 0)
        elif observation.get("calculatedTotalCost") is not None:
            totals["cost"] += float(observation["calculatedTotalCost"])
    return totals


def fetch_observations(
    trace: dict[str, Any],
    config: dict[str, str],
) -> list[dict[str, Any]]:
    trace_id = trace.get("id")
    if not isinstance(trace_id, str) or not trace_id:
        raise PitwallError("Langfuse trace response is missing id")
    payload = api_get("/api/public/observations", {"traceId": trace_id}, config)
    return response_rows(payload, "/api/public/observations")


def table_row(label: str, left: dict[str, Any], right: dict[str, Any]) -> str:
    values = [
        label,
        str(left["input"]),
        str(left["cache_read"]),
        str(left["cache_write"]),
        str(left["output"]),
        f"{left['cost']:.6f}",
        str(right["input"]),
        str(right["cache_read"]),
        str(right["cache_write"]),
        str(right["output"]),
        f"{right['cost']:.6f}",
    ]
    return " | ".join(values)


def optional_trace(traces: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for trace in traces:
        if trace.get("name") == name:
            return trace
    return None


def generations_for(
    trace: dict[str, Any] | None,
    config: dict[str, str],
) -> list[dict[str, Any]]:
    if trace is None:
        return []
    return [
        item
        for item in fetch_observations(trace, config)
        if item.get("type") == "GENERATION"
    ]


def report(experiment: str, expect_legs: str = "both") -> None:
    config = langfuse_config()
    tag = f"exp-{experiment}"
    payload = api_get("/api/public/traces", {"tags": tag}, config)
    traces = response_rows(payload, "/api/public/traces")
    # Single-lane and --skip-solo experiments legitimately carry ONE leg. Report
    # what exists and omit the ratio, rather than failing a run whose ingest
    # already succeeded. A leg the caller EXPECTED but did not get is still an
    # error: silently reporting one side would bias every comparison drawn from it.
    pitwall_trace = optional_trace(traces, "pitwall-leg")
    solo_trace = optional_trace(traces, "solo-leg")
    if pitwall_trace is None and solo_trace is None:
        raise PitwallError(
            f"experiment {experiment} has neither a pitwall-leg nor a solo-leg trace"
        )
    if expect_legs in {"both", "pitwall"} and pitwall_trace is None:
        raise PitwallError(
            f"experiment {experiment} expected a pitwall-leg trace but none was ingested"
        )
    if expect_legs in {"both", "solo"} and solo_trace is None:
        raise PitwallError(
            f"experiment {experiment} expected a solo-leg trace but none was ingested"
        )
    pitwall_generations = generations_for(pitwall_trace, config)
    solo_generations = generations_for(solo_trace, config)
    pitwall_total = observation_totals(pitwall_generations)
    solo_total = observation_totals(solo_generations)
    print(
        "bucket | pitwall input | pitwall cache_read | pitwall cache_write | "
        "pitwall output | pitwall cost USD | solo input | solo cache_read | "
        "solo cache_write | solo output | solo cost USD"
    )
    print(table_row("total", pitwall_total, solo_total))
    print()
    print("pitwall lane | input | cache_read | cache_write | output | cost USD")
    for observation in pitwall_generations:
        metadata = observation.get("metadata")
        lane = metadata.get("lane", observation.get("name", "?")) if isinstance(
            metadata, dict
        ) else observation.get("name", "?")
        totals = observation_totals([observation])
        print(
            f"{lane} | {totals['input']} | {totals['cache_read']} | "
            f"{totals['cache_write']} | {totals['output']} | "
            f"{totals['cost']:.6f}"
        )
    print()
    if pitwall_trace is None:
        print("pitwall / solo cost ratio: n/a (solo-only experiment)")
    elif solo_trace is None:
        print("pitwall / solo cost ratio: n/a (pitwall-only experiment)")
    elif solo_total["cost"] == 0:
        print("pitwall / solo cost ratio: n/a (solo cost is zero)")
    else:
        print(
            f"pitwall / solo cost ratio: "
            f"{pitwall_total['cost'] / solo_total['cost']:.6f}"
        )


def assert_not_already_ingested(trace: dict[str, Any]) -> None:
    """Ingest is additive: posting the same leg twice double-counts its cost.

    Langfuse has no upsert here, so the safe property is refusal, not merge.
    Checked against the live API; a lookup failure must not block the ingest.
    """
    experiment = trace["metadata"]["experiment_id"]
    name = trace["name"]
    try:
        config = langfuse_config()
        payload = api_get(
            "/api/public/traces", {"tags": f"exp-{experiment}"}, config
        )
        existing = optional_trace(response_rows(payload, "/api/public/traces"), name)
    except PitwallError as exc:
        print(
            f"warning: could not check for an existing {name} in experiment "
            f"{experiment} ({exc}); proceeding",
            file=sys.stderr,
        )
        return
    if existing is not None:
        raise AlreadyIngestedError(
            f"experiment {experiment} already has a {name} trace; ingesting again "
            f"would double-count its cost. Use a new --experiment id (one per run), "
            f"or --force to ingest anyway."
        )


def emit_or_post(trace: dict[str, Any], dry_run: bool, force: bool = False) -> None:
    if dry_run:
        print(json.dumps(trace, indent=2, sort_keys=True))
        return
    if not force:
        assert_not_already_ingested(trace)
    post_trace(trace)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Post pitwall attribution traces to Langfuse"
    )
    subparsers = result.add_subparsers(dest="command", required=True)

    lane = subparsers.add_parser("ingest-lane")
    lane.add_argument("--run-dir", required=True, type=Path)
    lane.add_argument("--experiment", required=True)
    lane.add_argument("--dry-run", action="store_true")
    lane.add_argument(
        "--force",
        action="store_true",
        help="ingest even if this experiment already has a pitwall-leg (double-counts)",
    )

    solo = subparsers.add_parser("ingest-solo")
    solo.add_argument("--json-file", required=True, type=Path)
    solo.add_argument("--experiment", required=True)
    solo.add_argument("--model")
    solo.add_argument("--dry-run", action="store_true")
    solo.add_argument(
        "--force",
        action="store_true",
        help="ingest even if this experiment already has a solo-leg (double-counts)",
    )

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--experiment", required=True)
    report_parser.add_argument(
        "--expect-legs",
        choices=("both", "pitwall", "solo"),
        default="both",
        help="which legs must be present; a missing expected leg is an error",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "ingest-lane":
            trace = build_lane_trace(args.run_dir, args.experiment)
            emit_or_post(trace, args.dry_run, args.force)
        elif args.command == "ingest-solo":
            trace = build_solo_trace(args.json_file, args.experiment, args.model)
            emit_or_post(trace, args.dry_run, args.force)
        else:
            report(args.experiment, args.expect_legs)
    except AlreadyIngestedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except PitwallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

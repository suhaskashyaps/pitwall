import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "run1"
MULTI_MODEL_FIXTURES = ROOT / "tests" / "fixtures" / "run1b"
SCRIPT = ROOT / "scripts" / "pitwall_trace.py"

SPEC = importlib.util.spec_from_file_location("pitwall_trace", SCRIPT)
assert SPEC and SPEC.loader
trace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trace)


def generations_by_lane(result):
    return {
        generation["metadata"]["lane"]: generation
        for generation in result["generations"]
    }


def test_lane_trace_parses_all_three_formats_with_exclusive_buckets(tmp_path):
    missing_lanes = tmp_path / "lanes.json"
    result = trace.build_lane_trace(
        FIXTURES,
        "demo",
        prices_path=ROOT / "config" / "prices.json",
        lanes_path=missing_lanes,
    )

    assert result["name"] == "pitwall-leg"
    assert result["tags"] == ["exp-demo", "mode:pitwall"]
    assert result["metadata"] == {
        "experiment_id": "demo",
        "mode": "pitwall",
        "skipped_captures": [],
        "missing_captures": [],
    }
    assert len(result["generations"]) == 3

    lanes = generations_by_lane(result)
    assert lanes["grok-lane"]["model"] == "grok-code-fast"
    assert lanes["grok-lane"]["usage_details"] == {
        "input": 7500,
        "cache_read": 2500,
        "cache_write": 0,
        "output": 1200,
    }
    assert lanes["grok-lane"]["cost_details"]["total"] == pytest.approx(0.00375)
    assert lanes["grok-lane"]["metadata"]["cost_source"] == "harness"

    assert lanes["codex-lane"]["model"] == "gpt-5.6-sol"
    assert lanes["codex-lane"]["usage_details"] == {
        "input": 15000,
        "cache_read": 5000,
        "cache_write": 1000,
        "output": 3000,
    }
    assert lanes["codex-lane"]["cost_details"]["total"] == pytest.approx(0.17375)
    assert lanes["codex-lane"]["metadata"]["cost_source"] == "imputed"

    assert lanes["claude-lane"]["model"] == "claude-sonnet-5"
    assert lanes["claude-lane"]["usage_details"] == {
        "input": 4000,
        "cache_read": 6000,
        "cache_write": 1500,
        "output": 2000,
    }
    assert lanes["claude-lane"]["cost_details"]["total"] == pytest.approx(0.098)
    assert lanes["claude-lane"]["metadata"]["cost_source"] == "harness"


def test_solo_trace_uses_anthropic_exclusive_buckets():
    result = trace.build_solo_trace(FIXTURES / "solo.json", "demo", None)
    generation = result["generations"][0]

    assert result["name"] == "solo-leg"
    assert result["tags"] == ["exp-demo", "mode:solo"]
    assert generation["model"] == "claude-sonnet-5"
    assert generation["usage_details"] == {
        "input": 6000,
        "cache_read": 8000,
        "cache_write": 2000,
        "output": 2500,
    }
    assert generation["cost_details"]["total"] == pytest.approx(0.134)
    assert generation["metadata"]["cost_source"] == "harness"


def test_lane_trace_emits_one_claude_generation_per_model_usage_entry(tmp_path):
    result = trace.build_lane_trace(
        MULTI_MODEL_FIXTURES,
        "demo2",
        prices_path=ROOT / "config" / "prices.json",
        lanes_path=tmp_path / "missing-lanes.json",
    )

    assert len(result["generations"]) == 2
    generations = {
        generation["model"]: generation for generation in result["generations"]
    }
    assert generations["claude-fable-5"]["name"] == "architect:claude-fable-5"
    assert generations["claude-fable-5"]["usage_details"] == {
        "input": 12,
        "cache_read": 228364,
        "cache_write": 32017,
        "output": 2318,
    }
    assert generations["claude-fable-5"]["cost_details"]["total"] == pytest.approx(
        0.9061164999999999
    )
    assert generations["claude-sonnet-5"]["name"] == "architect:claude-sonnet-5"
    assert generations["claude-sonnet-5"]["usage_details"] == {
        "input": 44,
        "cache_read": 496770,
        "cache_write": 22720,
        "output": 6525,
    }
    assert generations["claude-sonnet-5"]["cost_details"]["total"] == pytest.approx(
        0.33223800000000003
    )
    for generation in generations.values():
        assert generation["metadata"] == {
            "lane": "architect",
            "model_harness": "claude",
            "cost_source": "harness",
        }


def test_solo_model_fallback(tmp_path):
    fixture = json.loads((FIXTURES / "solo.json").read_text())
    fixture.pop("model")
    path = tmp_path / "solo-without-model.json"
    path.write_text(json.dumps(fixture))

    result = trace.build_solo_trace(path, "demo", "claude-haiku-4-5")
    assert result["generations"][0]["model"] == "claude-haiku-4-5"


def test_missing_price_is_loud():
    with pytest.raises(trace.PitwallError, match="missing price for model unknown-model"):
        trace.impute_cost(
            "unknown-model",
            {"input": 1, "cache_read": 1, "cache_write": 1, "output": 1},
            trace.load_prices(),
        )


def test_unparseable_lane_names_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")

    with pytest.raises(trace.PitwallError, match=r"bad\.json"):
        trace.build_lane_trace(
            tmp_path,
            "demo",
            prices_path=ROOT / "config" / "prices.json",
            lanes_path=tmp_path / "missing-lanes.json",
        )


def test_empty_run_directory_is_loud(tmp_path):
    with pytest.raises(trace.PitwallError, match="no lane result files"):
        trace.build_lane_trace(
            tmp_path,
            "demo",
            prices_path=ROOT / "config" / "prices.json",
            lanes_path=tmp_path / "missing-lanes.json",
        )


def test_parse_codex_reads_thread_turn_schema(tmp_path):
    path = tmp_path / "codex-lane.jsonl"
    events = [
        {"type": "thread.started", "thread_id": "t1"},
        {"type": "turn.started"},
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 20000,
                "cached_input_tokens": 5000,
                "cache_write_input_tokens": 1000,
                "output_tokens": 3000,
                "reasoning_output_tokens": 800,
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(event) for event in events), encoding="utf-8"
    )

    parsed = trace.parse_codex(
        path, "gpt-5.6-sol", trace.load_prices(ROOT / "config" / "prices.json")
    )

    assert parsed["usage_details"] == {
        "input": 15000,
        "cache_read": 5000,
        "cache_write": 1000,
        "output": 3000,
    }
    assert parsed["cost_details"]["total"] == pytest.approx(0.17375)
    assert parsed["harness_metadata"]["total_tokens"] == 23000


FAKE_PRICES = {
    "test-model": {
        "input_per_mtok": 2.0,
        "output_per_mtok": 10.0,
        "cache_read_per_mtok": 0.2,
        "cache_write_per_mtok": 2.5,
    }
}


def _grok_capture(**over):
    data = {
        "stopReason": "EndTurn",
        "usage": {
            "input_tokens": 1_000_000,
            "cache_read_input_tokens": 2_000_000,
            "output_tokens": 500_000,
            "reasoning_tokens": 0,
            "total_tokens": 3_500_000,
        },
        "modelUsage": {"test-model": {}},
        "num_turns": 1,
    }
    data.update(over)
    return data


def test_unpriced_model_is_fatal_not_silently_skipped(tmp_path):
    """The whole point of this module is not under-reporting cost. A capture we
    can READ but cannot price carries real spend and must abort, never be
    skipped like a dead dispatch."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grok-lane.json").write_text(
        json.dumps(_grok_capture()), encoding="utf-8"
    )
    prices = tmp_path / "prices.json"
    prices.write_text(json.dumps({"models": {}}), encoding="utf-8")

    with pytest.raises(trace.PitwallError, match="missing price for model"):
        trace.build_lane_trace(
            run_dir, "demo", prices_path=prices, lanes_path=tmp_path / "lanes.json"
        )


def test_zero_cost_with_usage_is_imputed_not_trusted():
    """A proxy may emit total_cost_usd as a 0 placeholder. Trusting it would
    report a lane that plainly burned tokens as free."""
    parsed = trace.parse_grok(
        Path("proxy.json"), _grok_capture(total_cost_usd=0), FAKE_PRICES
    )
    assert parsed["cost_source"] == "imputed"
    assert parsed["cost_details"]["total"] == pytest.approx(7.4)


def test_grok_cache_write_tokens_are_priced():
    data = _grok_capture(usage={
        "input_tokens": 2_000_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 1_000_000,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 3_000_000,
    })
    parsed = trace.parse_grok(Path("proxy.json"), data, FAKE_PRICES)
    assert parsed["usage_details"]["cache_write"] == 1_000_000
    # 1M input at $2 + 1M cache_write at $2.50
    assert parsed["cost_details"]["total"] == pytest.approx(4.5)


def test_parse_grok_imputes_cost_when_proxy_omits_total_cost_usd():
    """CLIProxyAPI-routed models report no total_cost_usd (the proxy knows no
    pricing). Cost must be imputed from the price table, not dropped to zero."""
    # Inline prices: binding to config/prices.json would break this test on a
    # routine price update (that table documents its own expiry dates).
    parsed = trace.parse_grok(Path("proxy-lane.json"), _grok_capture(), FAKE_PRICES)

    # cache_read > input means the counter is already exclusive: input stays 1M.
    assert parsed["usage_details"] == {
        "input": 1_000_000,
        "cache_read": 2_000_000,
        "cache_write": 0,
        "output": 500_000,
    }
    # 1M*$2 + 2M*$0.2 + 0.5M*$10 = 2.0 + 0.4 + 5.0
    assert parsed["cost_details"]["total"] == pytest.approx(7.4)
    assert parsed["cost_source"] == "imputed"


def test_parse_grok_prefers_harness_cost_when_present():
    prices = trace.load_prices(ROOT / "config" / "prices.json")
    data = {
        "stopReason": "EndTurn",
        "usage": {
            "input_tokens": 1000,
            "cache_read_input_tokens": 100,
            "output_tokens": 50,
            "reasoning_tokens": 0,
            "total_tokens": 1050,
        },
        "modelUsage": {"grok-4.5": {}},
        "num_turns": 1,
        "total_cost_usd": 0.123456,
    }
    parsed = trace.parse_grok(Path("native-lane.json"), data, prices)

    assert parsed["cost_details"]["total"] == pytest.approx(0.123456)
    assert parsed["cost_source"] == "harness"


def test_dead_dispatch_capture_is_skipped_not_fatal(tmp_path, capsys):
    """A zero-byte capture (dispatch died before the harness ran) must not
    destroy the sibling captures that did land."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in ("grok-lane.json", "claude-lane.json", "codex-lane.jsonl"):
        (run_dir / name).write_bytes((FIXTURES / name).read_bytes())
    (run_dir / "grok-dead.json").write_text("", encoding="utf-8")

    result = trace.build_lane_trace(
        run_dir,
        "demo",
        prices_path=ROOT / "config" / "prices.json",
        lanes_path=tmp_path / "lanes.json",
    )

    assert len(result["generations"]) == 3
    assert result["metadata"]["skipped_captures"] == ["grok-dead.json"]
    assert "grok-dead.json" in capsys.readouterr().err


def test_sidecar_without_capture_is_reported_as_missing(tmp_path, capsys):
    """A dispatch that wrote a sidecar but no capture spent money that is absent
    from the receipt. It must be named, not silently omitted."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in ("grok-lane.json", "claude-lane.json", "codex-lane.jsonl"):
        (run_dir / name).write_bytes((FIXTURES / name).read_bytes())
    (run_dir / "ghost-dispatch.meta.json").write_text(
        json.dumps({"lane": "ghost", "harness": "grok", "model": ""}), encoding="utf-8"
    )

    result = trace.build_lane_trace(
        run_dir,
        "demo",
        prices_path=ROOT / "config" / "prices.json",
        lanes_path=tmp_path / "lanes.json",
    )

    assert result["metadata"]["missing_captures"] == ["ghost-dispatch"]
    assert "ghost-dispatch" in capsys.readouterr().err


def test_sidecar_with_capture_is_not_flagged(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grok-lane.json").write_bytes((FIXTURES / "grok-lane.json").read_bytes())
    (run_dir / "grok-lane.meta.json").write_text(
        json.dumps({"lane": "grok-lane", "harness": "grok", "model": ""}),
        encoding="utf-8",
    )
    (run_dir / "codex-lane.jsonl").write_bytes(
        (FIXTURES / "codex-lane.jsonl").read_bytes()
    )
    (run_dir / "codex-lane.meta.json").write_text(
        json.dumps({"lane": "codex-lane", "harness": "codex", "model": "gpt-5.6-sol"}),
        encoding="utf-8",
    )

    assert trace.missing_dispatch_captures(run_dir) == []


def test_dead_codex_dispatch_does_not_abort_the_leg(tmp_path, capsys):
    """An empty .jsonl is a dead codex dispatch. It must be skipped like any
    other dead capture, not take every healthy sibling down with it."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grok-lane.json").write_bytes((FIXTURES / "grok-lane.json").read_bytes())
    (run_dir / "codex-dead.jsonl").write_text("", encoding="utf-8")
    (run_dir / "codex-dead.meta.json").write_text(
        json.dumps({"lane": "codex-dead", "harness": "codex", "model": "gpt-5.6-sol"}),
        encoding="utf-8",
    )

    result = trace.build_lane_trace(
        run_dir,
        "demo",
        prices_path=ROOT / "config" / "prices.json",
        lanes_path=tmp_path / "lanes.json",
    )

    assert len(result["generations"]) == 1
    assert result["metadata"]["skipped_captures"] == ["codex-dead.jsonl"]


def test_corrupt_sidecar_is_fatal_not_a_dropped_capture(tmp_path):
    """A corrupt sidecar describes a capture that DID land. Skipping it would
    discard real spend, so it must abort rather than under-report."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grok-lane.json").write_bytes((FIXTURES / "grok-lane.json").read_bytes())
    (run_dir / "grok-lane.meta.json").write_text("", encoding="utf-8")

    with pytest.raises(trace.PitwallError):
        trace.build_lane_trace(
            run_dir,
            "demo",
            prices_path=ROOT / "config" / "prices.json",
            lanes_path=tmp_path / "lanes.json",
        )


def test_zero_usage_capture_without_cost_does_not_crash():
    data = _grok_capture(usage={
        "input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    })
    parsed = trace.parse_grok(Path("empty.json"), data, {})
    assert parsed["cost_details"]["total"] == 0.0


def test_all_captures_unusable_is_fatal(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "grok-dead.json").write_text("", encoding="utf-8")

    with pytest.raises(trace.PitwallError, match="every lane capture was unusable"):
        trace.build_lane_trace(
            run_dir,
            "demo",
            prices_path=ROOT / "config" / "prices.json",
            lanes_path=tmp_path / "lanes.json",
        )


def _stub_langfuse(monkeypatch, traces):
    monkeypatch.setattr(trace, "langfuse_config", lambda: {"LANGFUSE_HOST": "x"})
    monkeypatch.setattr(trace, "api_get", lambda path, params, config: {"data": traces})


def test_second_ingest_of_same_leg_is_refused(monkeypatch):
    _stub_langfuse(monkeypatch, [{"name": "solo-leg", "id": "t1"}])
    payload = {"name": "solo-leg", "metadata": {"experiment_id": "demo"}}

    with pytest.raises(trace.AlreadyIngestedError, match="already has a solo-leg"):
        trace.assert_not_already_ingested(payload)


def test_first_ingest_is_allowed(monkeypatch):
    _stub_langfuse(monkeypatch, [{"name": "pitwall-leg", "id": "t1"}])
    trace.assert_not_already_ingested(
        {"name": "solo-leg", "metadata": {"experiment_id": "demo"}}
    )


def test_unreachable_langfuse_warns_but_does_not_block_ingest(monkeypatch, capsys):
    def boom():
        raise trace.PitwallError("no credentials")

    monkeypatch.setattr(trace, "langfuse_config", boom)
    trace.assert_not_already_ingested(
        {"name": "solo-leg", "metadata": {"experiment_id": "demo"}}
    )
    assert "could not check" in capsys.readouterr().err


def test_report_raises_when_an_expected_leg_is_missing(monkeypatch):
    _stub_langfuse(monkeypatch, [{"name": "solo-leg", "id": "t1"}])
    monkeypatch.setattr(trace, "fetch_observations", lambda t, c: [])

    with pytest.raises(trace.PitwallError, match="expected a pitwall-leg"):
        trace.report("demo", expect_legs="both")


def test_report_allows_a_deliberately_single_leg_experiment(monkeypatch, capsys):
    _stub_langfuse(monkeypatch, [{"name": "solo-leg", "id": "t1"}])
    monkeypatch.setattr(trace, "fetch_observations", lambda t, c: [])

    trace.report("demo", expect_legs="solo")
    assert "n/a (solo-only experiment)" in capsys.readouterr().out


def test_parse_codex_turn_completed_without_usage_is_loud(tmp_path):
    path = tmp_path / "codex-lane.jsonl"
    path.write_text(json.dumps({"type": "turn.completed"}), encoding="utf-8")

    with pytest.raises(trace.PitwallError, match="turn.completed is missing usage"):
        trace.parse_codex(
            path, "gpt-5.6-sol", trace.load_prices(ROOT / "config" / "prices.json")
        )

import json
from pathlib import Path

import pytest

from tools import publish_cpi_prediction_markets as pub


def _fit_row(measure, ref_month, as_of, mu, *, n_params=3):
    return {
        "measure": measure,
        "ref_month": ref_month,
        "as_of_ts": f"{as_of}T18:00:00+00:00",
        "mu": mu,
        "b": 0.4,
        "g": -0.05,
        "h": 0.03,
        "c": 0.0,
        "q": 0.0,
        "n_params": n_params,
        "implied_mean": mu,
        "implied_median": mu - 0.02,
        "skew": -0.3,
        "kurt": 3.4,
        "medcouple": -0.1,
        "prob_mad_err": 0.012,
        "n_strikes": 7,
        "axis_unit": "YoY %" if measure.endswith("yoy") else "MoM %",
        "repaired": False,
        "max_abs_adjustment": 0.0,
        "n_violations": 0,
        "fit_datetime": f"{as_of} 18:00:00",
        "model_version": "gh_prediction_v1",
    }


def _ladder_points(centre):
    return [
        {"strike": centre - 0.5, "implied_prob": 0.82},
        {"strike": centre - 0.25, "implied_prob": 0.70},
        {"strike": centre, "implied_prob": 0.52},
        {"strike": centre + 0.25, "implied_prob": 0.33},
        {"strike": centre + 0.5, "implied_prob": 0.18},
    ]


def _sources(measures=("headline_yoy", "core_yoy", "headline_mom", "core_mom")):
    gh_fit = {}
    ladders = {}
    centres = {"headline_yoy": 3.1, "core_yoy": 3.4, "headline_mom": 0.25, "core_mom": 0.3}
    for measure in measures:
        centre = centres[measure]
        row = _fit_row(measure, "2026-01", "2026-02-10", centre)
        gh_fit[measure] = [row]
        ladders[(measure, "2026-01", "2026-02-10")] = _ladder_points(centre)
    return {"gh_fit": gh_fit, "ladders": ladders}


def test_build_payload_matches_schema():
    payload = pub.build_payload(_sources(), generated_at_utc="2026-02-11T00:00:00+00:00")
    assert payload["schema_version"] == "cpi_prediction_markets_v1"
    # The public model identifier is NEUTRAL: the fitting method is confidential
    # and must not be named/inferable in the public JSON (so not "gh_prediction_v1").
    assert payload["model_version"] == "implied_dist_v1"
    assert payload["latest_as_of"] == "2026-02-10"
    assert payload["warning"] is None
    assert {m["measure"] for m in payload["measures"]} == {
        "headline_yoy", "core_yoy", "headline_mom", "core_mom"
    }
    entry = payload["measures"][0]
    # Confidentiality: the fitted-distribution parameter count must NOT be
    # published, and no GH/Tukey token may appear anywhere in the payload.
    assert "n_params" not in entry
    blob = json.dumps(payload).lower()
    for token in ("n_params", "gh_prediction", "tukey", "gh param"):
        assert token not in blob, f"confidential token leaked into public payload: {token}"
    curve = entry["curve"]
    assert len(curve["x"]) == len(curve["cdf"]) == len(curve["pdf"]) > 1
    # CDF is monotone non-decreasing and bounded in [0, 1].
    assert all(0.0 <= v <= 1.0 for v in curve["cdf"])
    assert all(curve["cdf"][i + 1] >= curve["cdf"][i] - 1e-9 for i in range(len(curve["cdf"]) - 1))
    assert entry["market_points"]
    assert entry["implied_mean"] is not None


def test_missing_measure_produces_warning():
    sources = _sources(measures=("headline_yoy", "core_yoy", "headline_mom"))
    payload = pub.build_payload(sources, generated_at_utc="2026-02-11T00:00:00+00:00")
    assert "core_mom" in payload["warning"]
    assert {m["measure"] for m in payload["measures"]} == {
        "headline_yoy", "core_yoy", "headline_mom"
    }


def test_malformed_fit_skipped_not_crashed():
    sources = _sources(measures=("headline_yoy",))
    # Corrupt the single fit's shape parameters to non-finite.
    sources["gh_fit"]["headline_yoy"][0]["mu"] = float("nan")
    payload = pub.build_payload(sources, generated_at_utc="2026-02-11T00:00:00+00:00")
    assert payload["measures"] == []
    assert "headline_yoy" in payload["warning"]


def test_empty_sources_degrade_gracefully():
    payload = pub.build_payload({"gh_fit": {}, "ladders": {}})
    assert payload["measures"] == []
    assert payload["latest_as_of"] is None
    assert payload["warning"] is not None


def test_latest_fit_per_ref_month_keeps_most_recent():
    rows = [
        _fit_row("headline_yoy", "2026-01", "2026-02-05", 3.0),
        _fit_row("headline_yoy", "2026-01", "2026-02-10", 3.2),
    ]
    latest = pub._latest_fit_per_ref_month(rows)
    assert len(latest) == 1
    assert latest[0]["as_of_ts"].startswith("2026-02-10")


def test_stable_generated_at_when_unchanged(tmp_path, monkeypatch):
    target = tmp_path / "cpi_prediction_markets.json"
    sources = _sources()

    calls = {"n": 0}

    def fake_now():
        calls["n"] += 1
        return f"2026-02-11T00:00:0{calls['n']}+00:00"

    monkeypatch.setattr(pub, "_now_utc", fake_now)

    first = pub.publish(target, sources=sources)
    stored_first = json.loads(target.read_text())["generated_at_utc"]
    assert stored_first == first["generated_at_utc"]

    second = pub.publish(target, sources=sources)
    stored_second = json.loads(target.read_text())["generated_at_utc"]
    # Content is unchanged, so the timestamp is reused despite _now_utc advancing.
    assert stored_second == stored_first


def test_timestamp_moves_when_content_changes(tmp_path, monkeypatch):
    target = tmp_path / "cpi_prediction_markets.json"
    counter = {"n": 0}

    def fake_now():
        counter["n"] += 1
        return f"2026-02-1{counter['n']}T00:00:00+00:00"

    monkeypatch.setattr(pub, "_now_utc", fake_now)

    pub.publish(target, sources=_sources())
    first = json.loads(target.read_text())["generated_at_utc"]

    # Drop a measure -> content changes -> timestamp advances.
    pub.publish(target, sources=_sources(measures=("headline_yoy", "core_yoy")))
    second = json.loads(target.read_text())["generated_at_utc"]
    assert second != first

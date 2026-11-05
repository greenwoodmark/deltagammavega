import json
from pathlib import Path

import pytest

from tools import validate_cpi_prediction_markets_data as val


def _good_payload():
    x = [0.0, 0.5, 1.0, 1.5, 2.0]
    cdf = [0.05, 0.2, 0.5, 0.8, 0.95]
    pdf = [0.1, 0.3, 0.4, 0.3, 0.1]
    measures = []
    for measure, axis_unit in (
        ("headline_yoy", "YoY %"),
        ("core_yoy", "YoY %"),
        ("headline_mom", "MoM %"),
        ("core_mom", "MoM %"),
    ):
        measures.append(
            {
                "measure": measure,
                "reference_month": "2026-01",
                "as_of": "2026-02-10",
                "axis_unit": axis_unit,
                "implied_mean": 3.1,
                "implied_median": 3.0,
                "n_strikes": 7,
                "repaired": False,
                "prob_mad_err": 0.012,
                "curve": {"x": x, "cdf": cdf, "pdf": pdf},
                "market_points": [
                    {"strike": 0.5, "implied_prob": 0.8},
                    {"strike": 1.0, "implied_prob": 0.5},
                ],
            }
        )
    return {
        "schema_version": "cpi_prediction_markets_v1",
        "generated_at_utc": "2026-02-11T00:00:00+00:00",
        "latest_as_of": "2026-02-10",
        "model_version": "implied_dist_v1",
        "warning": None,
        "measures": measures,
    }


def _write(tmp_path: Path, payload) -> Path:
    path = tmp_path / "cpi_prediction_markets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_accepts_good_payload(tmp_path):
    payload = val.validate(_write(tmp_path, _good_payload()))
    assert len(payload["measures"]) == 4


def test_rejects_missing_measure(tmp_path):
    payload = _good_payload()
    payload["measures"] = payload["measures"][:-1]
    with pytest.raises(ValueError, match="measures incomplete"):
        val.validate(_write(tmp_path, payload))


def test_rejects_wrong_schema(tmp_path):
    payload = _good_payload()
    payload["schema_version"] = "other_v9"
    with pytest.raises(ValueError, match="schema is incompatible"):
        val.validate(_write(tmp_path, payload))


def test_rejects_missing_top_level_field(tmp_path):
    payload = _good_payload()
    del payload["model_version"]
    with pytest.raises(ValueError, match="top-level payload fields missing"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_top_level_field(tmp_path):
    payload = _good_payload()
    payload["extra_metadata"] = {}
    with pytest.raises(ValueError, match="top-level payload fields unknown"):
        val.validate(_write(tmp_path, payload))


def test_rejects_missing_measure_field(tmp_path):
    payload = _good_payload()
    del payload["measures"][0]["implied_mean"]
    with pytest.raises(ValueError, match="measure entry fields missing"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_measure_field(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["extra_metadata"] = {}
    with pytest.raises(ValueError, match="measure entry fields unknown"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_curve_field(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["extra_axis"] = []
    with pytest.raises(ValueError, match="curve fields unknown"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_market_point_field(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["market_points"][0]["quote"] = 0.8
    with pytest.raises(ValueError, match="market point fields unknown"):
        val.validate(_write(tmp_path, payload))


def test_rejects_mismatched_curve_lengths(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["pdf"] = [0.1, 0.2]
    with pytest.raises(ValueError, match="mismatched lengths"):
        val.validate(_write(tmp_path, payload))


def test_rejects_non_finite_number(tmp_path):
    path = tmp_path / "bad.json"
    raw = json.dumps(_good_payload()).replace('"implied_mean": 3.1', '"implied_mean": NaN')
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        val.validate(path)


def test_rejects_non_monotone_curve_axis(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["x"] = [0.0, 0.5, 0.4, 1.5, 2.0]
    with pytest.raises(ValueError, match="strictly increasing"):
        val.validate(_write(tmp_path, payload))


def test_rejects_cdf_out_of_range(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["cdf"] = [0.05, 0.2, 1.4, 0.8, 0.95]
    with pytest.raises(ValueError, match=r"cdf must lie"):
        val.validate(_write(tmp_path, payload))


def test_rejects_negative_density(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["pdf"][2] = -0.1
    with pytest.raises(ValueError, match="pdf must be non-negative"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_measure(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["measure"] = "bogus_measure"
    with pytest.raises(ValueError, match="unknown measure"):
        val.validate(_write(tmp_path, payload))


def test_rejects_duplicate_measure(tmp_path):
    payload = _good_payload()
    payload["measures"].append(dict(payload["measures"][0]))
    with pytest.raises(ValueError, match="duplicate measure entry"):
        val.validate(_write(tmp_path, payload))


def test_rejects_bad_market_point(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["market_points"][0]["implied_prob"] = 1.7
    with pytest.raises(ValueError, match="implied_prob must lie"):
        val.validate(_write(tmp_path, payload))


def test_rejects_non_monotone_market_points(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["market_points"][1]["strike"] = 0.5
    with pytest.raises(ValueError, match="market_points.strike must be strictly increasing"):
        val.validate(_write(tmp_path, payload))

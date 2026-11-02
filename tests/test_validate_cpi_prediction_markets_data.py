import json
from pathlib import Path

import pytest

from tools import validate_cpi_prediction_markets_data as val


def _good_payload():
    x = [0.0, 0.5, 1.0, 1.5, 2.0]
    cdf = [0.05, 0.2, 0.5, 0.8, 0.95]
    pdf = [0.1, 0.3, 0.4, 0.3, 0.1]
    return {
        "schema_version": "cpi_prediction_markets_v1",
        "generated_at_utc": "2026-02-11T00:00:00+00:00",
        "latest_as_of": "2026-02-10",
        "model_version": "implied_dist_v1",
        "warning": None,
        "measures": [
            {
                "measure": "headline_yoy",
                "reference_month": "2026-01",
                "as_of": "2026-02-10",
                "axis_unit": "YoY %",
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
        ],
    }


def _write(tmp_path: Path, payload) -> Path:
    path = tmp_path / "cpi_prediction_markets.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_accepts_good_payload(tmp_path):
    payload = val.validate(_write(tmp_path, _good_payload()))
    assert len(payload["measures"]) == 1


def test_rejects_wrong_schema(tmp_path):
    payload = _good_payload()
    payload["schema_version"] = "other_v9"
    with pytest.raises(ValueError, match="schema is incompatible"):
        val.validate(_write(tmp_path, payload))


def test_rejects_missing_top_level_field(tmp_path):
    payload = _good_payload()
    del payload["model_version"]
    with pytest.raises(ValueError, match="top-level fields missing"):
        val.validate(_write(tmp_path, payload))


def test_rejects_missing_measure_field(tmp_path):
    payload = _good_payload()
    del payload["measures"][0]["implied_mean"]
    with pytest.raises(ValueError, match="missing fields"):
        val.validate(_write(tmp_path, payload))


def test_rejects_mismatched_curve_lengths(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["pdf"] = [0.1, 0.2]
    with pytest.raises(ValueError, match="mismatched lengths"):
        val.validate(_write(tmp_path, payload))


def test_rejects_non_finite_number(tmp_path):
    # NaN as a bare JSON constant must be rejected by parse_constant.
    path = tmp_path / "bad.json"
    raw = json.dumps(_good_payload())
    raw = raw.replace('"implied_mean": 3.1', '"implied_mean": NaN')
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        val.validate(path)


def test_rejects_non_monotone_cdf_axis(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["x"] = [0.0, 0.5, 0.4, 1.5, 2.0]
    with pytest.raises(ValueError, match="strictly increasing"):
        val.validate(_write(tmp_path, payload))


def test_rejects_cdf_out_of_range(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["curve"]["cdf"] = [0.05, 0.2, 1.4, 0.8, 0.95]
    with pytest.raises(ValueError, match=r"cdf must lie"):
        val.validate(_write(tmp_path, payload))


def test_rejects_unknown_measure(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["measure"] = "bogus_measure"
    with pytest.raises(ValueError, match="unknown measure"):
        val.validate(_write(tmp_path, payload))


def test_rejects_bad_market_point(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["market_points"][0]["implied_prob"] = 1.7
    with pytest.raises(ValueError, match="implied_prob must lie"):
        val.validate(_write(tmp_path, payload))


def test_rejects_forbidden_private_field(tmp_path):
    payload = _good_payload()
    payload["measures"][0]["source_uri"] = "gs://private/thing"
    with pytest.raises(ValueError, match="forbidden private fields"):
        val.validate(_write(tmp_path, payload))


@pytest.mark.parametrize("token", ["n_params", "gh_prediction_v1", "tukey"])
def test_rejects_confidential_method_fields(tmp_path, token):
    """The fitting method is confidential: a payload that leaks the parameter
    count or any GH/Tukey token must be rejected, not silently published."""
    payload = _good_payload()
    payload["measures"][0][token] = 3 if token == "n_params" else "x"
    with pytest.raises(ValueError, match="forbidden private fields"):
        val.validate(_write(tmp_path, payload))

"""Validate the public US CPI prediction-markets implied-distribution JSON.

Mirrors the shape and strictness of ``validate_softs_diagnostics.py`` and
``validate_uscpi_public_data.py``: reject non-finite JSON constants, forbid
private/internal fields, enforce the schema version, the top-level required
fields, the per-measure structure, finite numeric arrays, and matching array
lengths for the reconstructed curve. Stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SCHEMA = "cpi_prediction_markets_v1"
MEASURES = {"headline_yoy", "core_yoy", "headline_mom", "core_mom"}
AXIS_UNITS = {"YoY %", "MoM %", ""}
TOP_LEVEL_REQUIRED = {
    "schema_version",
    "generated_at_utc",
    "latest_as_of",
    "model_version",
    "warning",
    "measures",
}
MEASURE_REQUIRED = {
    "measure",
    "reference_month",
    "as_of",
    "axis_unit",
    "implied_mean",
    "implied_median",
    "n_strikes",
    "repaired",
    "prob_mad_err",
    "curve",
    "market_points",
}
FORBIDDEN_FIELDS = {
    "source_uri",
    "source_generation",
    "credentials",
    "private_key",
    "client_secret",
    "local_path",
    "traceback",
    "GOOGLE_APPLICATION_CREDENTIALS",
    # The fitting METHOD is confidential and must never be named or inferable in
    # the public JSON. Reject any field that would reveal it.
    "n_params",
    "gh_prediction",
    "gh_prediction_v1",
    "tukey",
    "gh_params",
}


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _finite_or_null(value: object, field: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be finite numeric or null")


def _finite_number(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number")


def _nonneg_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _validate_curve(curve: object, where: str) -> None:
    if not isinstance(curve, dict):
        raise ValueError(f"{where} curve must be an object")
    arrays = {}
    for key in ("x", "cdf", "pdf"):
        values = curve.get(key)
        if not isinstance(values, list):
            raise ValueError(f"{where} curve.{key} must be a list")
        for value in values:
            _finite_number(value, f"{where} curve.{key}[]")
        arrays[key] = values
    lengths = {len(values) for values in arrays.values()}
    if len(lengths) != 1:
        raise ValueError(f"{where} curve arrays have mismatched lengths: {sorted(lengths)}")
    length = lengths.pop()
    if length:
        xs = arrays["x"]
        if any(xs[i + 1] <= xs[i] for i in range(len(xs) - 1)):
            raise ValueError(f"{where} curve.x must be strictly increasing")
        for value in arrays["cdf"]:
            if not (0.0 - 1e-9 <= value <= 1.0 + 1e-9):
                raise ValueError(f"{where} curve.cdf must lie in [0, 1]")
        for value in arrays["pdf"]:
            if value < -1e-9:
                raise ValueError(f"{where} curve.pdf must be non-negative")


def _validate_measure(entry: object) -> None:
    if not isinstance(entry, dict):
        raise ValueError("measure entry must be an object")
    missing = sorted(MEASURE_REQUIRED.difference(entry))
    if missing:
        raise ValueError(f"measure entry missing fields: {missing}")
    measure = entry["measure"]
    if measure not in MEASURES:
        raise ValueError(f"unknown measure: {measure}")
    where = f"measure {measure}"
    if not isinstance(entry["reference_month"], str) or not entry["reference_month"]:
        raise ValueError(f"{where} reference_month must be a non-empty string")
    if not isinstance(entry["as_of"], str) or not entry["as_of"]:
        raise ValueError(f"{where} as_of must be a non-empty string")
    if entry["axis_unit"] not in AXIS_UNITS:
        raise ValueError(f"{where} axis_unit is invalid: {entry['axis_unit']}")
    _finite_or_null(entry["implied_mean"], f"{where} implied_mean")
    _finite_or_null(entry["implied_median"], f"{where} implied_median")
    _finite_or_null(entry["prob_mad_err"], f"{where} prob_mad_err")
    _nonneg_int(entry["n_strikes"], f"{where} n_strikes")
    if not isinstance(entry["repaired"], bool):
        raise ValueError(f"{where} repaired must be boolean")
    _validate_curve(entry["curve"], where)
    points = entry["market_points"]
    if not isinstance(points, list):
        raise ValueError(f"{where} market_points must be a list")
    for point in points:
        if not isinstance(point, dict) or set(point) != {"strike", "implied_prob"}:
            raise ValueError(f"{where} market_points entry must have strike + implied_prob")
        _finite_number(point["strike"], f"{where} market_points.strike")
        prob = point["implied_prob"]
        _finite_number(prob, f"{where} market_points.implied_prob")
        if not (0.0 - 1e-9 <= prob <= 1.0 + 1e-9):
            raise ValueError(f"{where} market_points.implied_prob must lie in [0, 1]")


def validate(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    leaked = sorted(field for field in FORBIDDEN_FIELDS if f'"{field}"' in text)
    if leaked:
        raise ValueError(f"forbidden private fields present: {leaked}")
    payload = json.loads(text, parse_constant=_reject_constant)
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    missing = sorted(TOP_LEVEL_REQUIRED.difference(payload))
    if missing:
        raise ValueError(f"top-level fields missing: {missing}")
    if payload.get("schema_version") != SCHEMA:
        raise ValueError("prediction-markets schema is incompatible")
    if not isinstance(payload.get("generated_at_utc"), str) or not payload["generated_at_utc"]:
        raise ValueError("generated_at_utc must be a non-empty string")
    if not isinstance(payload.get("model_version"), str) or not payload["model_version"]:
        raise ValueError("model_version must be a non-empty string")
    latest = payload.get("latest_as_of")
    if latest is not None and not isinstance(latest, str):
        raise ValueError("latest_as_of must be a string or null")
    warning = payload.get("warning")
    if warning is not None and not isinstance(warning, str):
        raise ValueError("warning must be a string or null")
    measures = payload.get("measures")
    if not isinstance(measures, list):
        raise ValueError("measures must be a list")
    seen = set()
    for entry in measures:
        _validate_measure(entry)
        if entry["measure"] in seen:
            raise ValueError(f"duplicate measure entry: {entry['measure']}")
        seen.add(entry["measure"])
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, nargs="?", default=Path("data/cpi_prediction_markets.json"))
    args = parser.parse_args()
    payload = validate(args.path)
    print(f"Validated {args.path}: measures={len(payload['measures'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

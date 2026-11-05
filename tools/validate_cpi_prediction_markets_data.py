"""Validate the public US CPI prediction-markets JSON contract.

The validator is stdlib-only and checks the complete neutral schema. Every
object uses an exact allowlist of fields so generated output cannot carry
unapproved source, implementation, or operational metadata.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

SCHEMA = "cpi_prediction_markets_v1"
MEASURES = {"headline_yoy", "core_yoy", "headline_mom", "core_mom"}
AXIS_UNITS = {"YoY %", "MoM %", ""}
TOP_LEVEL_FIELDS = {
    "schema_version",
    "generated_at_utc",
    "latest_as_of",
    "model_version",
    "warning",
    "measures",
}
MEASURE_FIELDS = {
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
CURVE_FIELDS = {"x", "cdf", "pdf"}
MARKET_POINT_FIELDS = {"strike", "implied_prob"}


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object field: {key}")
        result[key] = value
    return result


def _check_fields(value: object, allowed: set[str], where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be an object")
    fields = set(value)
    missing = sorted(allowed - fields)
    if missing:
        raise ValueError(f"{where} fields missing: {missing}")
    unknown = sorted(fields - allowed)
    if unknown:
        raise ValueError(f"{where} fields unknown: {unknown}")
    return value


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
    curve = _check_fields(curve, CURVE_FIELDS, f"{where} curve")
    arrays: dict[str, list[object]] = {}
    for key in ("x", "cdf", "pdf"):
        values = curve[key]
        if not isinstance(values, list):
            raise ValueError(f"{where} curve.{key} must be a list")
        for value in values:
            _finite_number(value, f"{where} curve.{key}[]")
        arrays[key] = values

    lengths = {len(values) for values in arrays.values()}
    if len(lengths) != 1:
        raise ValueError(f"{where} curve arrays have mismatched lengths: {sorted(lengths)}")

    xs = arrays["x"]
    if any(xs[index + 1] <= xs[index] for index in range(len(xs) - 1)):
        raise ValueError(f"{where} curve.x must be strictly increasing")
    for value in arrays["cdf"]:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{where} curve.cdf must lie in [0, 1]")
    for value in arrays["pdf"]:
        if value < 0.0:
            raise ValueError(f"{where} curve.pdf must be non-negative")


def _validate_measure(entry: object) -> str:
    entry = _check_fields(entry, MEASURE_FIELDS, "measure entry")
    measure = entry["measure"]
    if measure not in MEASURES:
        raise ValueError(f"unknown measure: {measure}")
    where = f"measure {measure}"

    for field in ("reference_month", "as_of"):
        if not isinstance(entry[field], str) or not entry[field]:
            raise ValueError(f"{where} {field} must be a non-empty string")
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
    previous_strike = None
    for point in points:
        point = _check_fields(point, MARKET_POINT_FIELDS, f"{where} market point")
        strike = point["strike"]
        _finite_number(strike, f"{where} market_points.strike")
        if previous_strike is not None and strike <= previous_strike:
            raise ValueError(f"{where} market_points.strike must be strictly increasing")
        previous_strike = strike
        _finite_number(point["implied_prob"], f"{where} market_points.implied_prob")
        if not 0.0 <= point["implied_prob"] <= 1.0:
            raise ValueError(f"{where} market_points.implied_prob must lie in [0, 1]")
    return measure


def validate(path: Path) -> dict[str, object]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_constant=_reject_constant,
        object_pairs_hook=_reject_duplicate_keys,
    )
    payload = _check_fields(payload, TOP_LEVEL_FIELDS, "top-level payload")
    if payload["schema_version"] != SCHEMA:
        raise ValueError("prediction-markets schema is incompatible")
    if not isinstance(payload["generated_at_utc"], str) or not payload["generated_at_utc"]:
        raise ValueError("generated_at_utc must be a non-empty string")
    if not isinstance(payload["model_version"], str) or not payload["model_version"]:
        raise ValueError("model_version must be a non-empty string")
    latest = payload["latest_as_of"]
    if latest is not None and (not isinstance(latest, str) or not latest):
        raise ValueError("latest_as_of must be a non-empty string or null")
    warning = payload["warning"]
    if warning is not None and not isinstance(warning, str):
        raise ValueError("warning must be a string or null")

    measures = payload["measures"]
    if not isinstance(measures, list):
        raise ValueError("measures must be a list")
    seen: set[str] = set()
    for entry in measures:
        measure = _validate_measure(entry)
        if measure in seen:
            raise ValueError(f"duplicate measure entry: {measure}")
        seen.add(measure)
    if seen != MEASURES:
        missing = sorted(MEASURES - seen)
        raise ValueError(f"measures incomplete; missing: {missing}")
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

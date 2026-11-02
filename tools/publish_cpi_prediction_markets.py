"""Build the public US CPI prediction-markets implied-distribution JSON.

Bridges the trading_env Phase 3 Kalshi GH-fit output (stored in the
``systematicpositiveskew`` GCS data lake) into a single public-safe JSON file
consumed by ``site/shared/cpi_prediction_markets.html``.

Design notes
------------
This website repository is deliberately lightweight: its REQUIRED path (the
static page plus ``build_site.py`` and the validators) is stdlib-only and
browser-only, so it carries no heavy Python runtime dependency. The GCS/parquet
read therefore lives behind a mockable boundary (``read_sources`` /
``_read_gh_fit`` / ``_read_raw_ladders``) and ``pyarrow``/``numpy`` are imported
lazily inside those helpers. The publisher is meant to run on the same box that
runs the trading_env pipeline, where ``pyarrow`` + GCS credentials + ``numpy``
are available. Tests drive the pure-Python emit path with local fixtures and
never touch the network or real GCS.

Source datasets (Hive-partitioned, read via pyarrow.dataset — NEVER
``pd.read_parquet`` on a partitioned path, matching the trading_env convention):

    gs://systematicpositiveskew/prediction_markets/kalshi_gh_fit/
        measure={M}/ref_month={YYYY-MM}/{as_of}.parquet   (one row per market)
    gs://systematicpositiveskew/prediction_markets/kalshi/
        measure={M}/ref_month={YYYY-MM}/{as_of}.parquet   (raw ladders)

The emitted curve is reconstructed publisher-side from the stored GH parameters
``(mu, b, g, h, c, q)`` using the same additive-location GH math as
trading_env's ``models/GH/sps_AH/ivmodel`` (centre the GH shape on zero, place
it at ``mu``, read off the survival function). This is the lighter path: no
curve is persisted upstream and the page only plots.

The output JSON is public-safe: only derived model outputs and market-implied
probabilities, never credentials, source URIs or raw internal fields.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

SCHEMA_VERSION = "cpi_prediction_markets_v1"
# Public-facing model identifier. Deliberately NEUTRAL: the fitting method is
# confidential and must not be named or inferable in the public JSON (so this is
# "implied_dist_v1", not the internal "gh_prediction_v1" fit model version).
MODEL_VERSION = "implied_dist_v1"

GH_FIT_BUCKET = "gs://systematicpositiveskew/prediction_markets/kalshi_gh_fit"
RAW_BUCKET = "gs://systematicpositiveskew/prediction_markets/kalshi"

MEASURES: tuple[str, ...] = ("headline_yoy", "core_yoy", "headline_mom", "core_mom")

# Reconstruction grid resolution. Kept modest so the emitted JSON stays small
# and the page plots a smooth curve without a heavy payload.
CURVE_POINTS = 121
TRUNCPOINT = 4.5
ZSTEPS = 1500
AXIS_PAD_FRAC = 0.15  # pad the strike axis beyond the observed ladder span


# ---------------------------------------------------------------------------
# GH reconstruction (self-contained; mirrors trading_env ivmodel additive math).
# numpy is imported lazily so the module import stays stdlib-only.
# ---------------------------------------------------------------------------

def _gh_outcome_sample(mu, b, g, h, c, q):
    """Return ``(outcome, P)`` for the GH shape placed at additive location mu.

    Mirrors ``ivmodel.GH_digital_outcome_sample``: build the standard-normal grid
    ``Z`` with probabilities ``P``, realise ``X = GCHQrealisation(Z,0,b,g,h,c,q)``,
    centre it on zero, then shift by ``mu``.
    """
    import numpy as np

    zsteps = ZSTEPS
    truncpoint = TRUNCPOINT
    Z = np.linspace(-(1 - 1 / zsteps), (1 - 1 / zsteps), num=zsteps, endpoint=True) * truncpoint
    import scipy.stats  # available on the publishing box alongside the trading_env math

    ulim = Z + truncpoint / zsteps
    llim = Z - truncpoint / zsteps
    P = scipy.stats.norm(0, 1).cdf(ulim) - scipy.stats.norm(0, 1).cdf(llim)
    P = P / np.sum(P)

    gg = g if abs(g) > 1e-12 else 1e-12
    X = (b / gg) * (np.exp(Z * gg) - 1) * np.exp(
        0.5 * h * Z**2 + 0.125 * c * Z**3 + (1 / 32) * q * Z**4
    )
    X = X - np.dot(X, P)         # centre the GH shape on zero
    outcome = mu + X             # additive location on the rate axis
    return outcome, P


def _reconstruct_curve(
    fit: Mapping[str, Any],
    strike_min: float,
    strike_max: float,
) -> dict[str, list[float]]:
    """Reconstruct a sampled implied CDF/PDF over a padded strike axis.

    ``cdf[i] = P(outcome < x[i])`` and ``pdf`` is the finite-difference density
    of that CDF (so ``pdf`` has the same length as ``x`` via a centred/edge
    difference). All arrays share the same length ``CURVE_POINTS``.
    """
    import numpy as np

    mu = float(fit["mu"])
    b = float(fit["b"])
    g = float(fit["g"])
    h = float(fit["h"])
    c = float(fit.get("c", 0.0) or 0.0)
    q = float(fit.get("q", 0.0) or 0.0)

    span = max(strike_max - strike_min, 1e-6)
    pad = span * AXIS_PAD_FRAC
    lo = strike_min - pad
    hi = strike_max + pad
    x = np.linspace(lo, hi, CURVE_POINTS)

    outcome, P = _gh_outcome_sample(mu, b, g, h, c, q)
    # Survival S(K) = P(outcome >= K); CDF F(K) = 1 - S(K).
    mask = outcome.reshape(-1, 1) >= x.reshape(1, -1)
    survival = (P.reshape(1, -1) @ mask).reshape(-1)
    cdf = np.clip(1.0 - survival, 0.0, 1.0)
    # PDF as the gradient of the CDF w.r.t. the strike axis (non-negative up to
    # numerical noise; clipped so the page never plots a negative density).
    pdf = np.clip(np.gradient(cdf, x), 0.0, None)

    return {
        "x": [float(v) for v in x],
        "cdf": [float(v) for v in cdf],
        "pdf": [float(v) for v in pdf],
    }


# ---------------------------------------------------------------------------
# Mockable GCS/parquet boundary (lazy pyarrow import; never hit in tests).
# ---------------------------------------------------------------------------

def _read_gh_fit(measure: str, bucket_base: str) -> list[dict[str, Any]]:
    """Read the GH-fit rows for one measure as a list of plain dicts.

    Uses pyarrow.dataset with hive partitioning so ``ref_month`` / ``as_of_ts``
    partition keys are recovered. Returns ``[]`` when the measure partition is
    absent. Imported lazily; tests monkeypatch ``read_sources`` and never reach
    this helper.
    """
    import pyarrow.dataset as ds  # lazy: keeps module import stdlib-only

    measure_path = f"{bucket_base}/measure={measure}"
    try:
        dataset = ds.dataset(measure_path, format="parquet", partitioning="hive")
    except FileNotFoundError:
        return []
    table = dataset.to_table()
    rows = table.to_pylist()
    for row in rows:
        row.setdefault("measure", measure)
    return rows


def _read_raw_ladders(measure: str, ref_month: str, as_of: str, bucket_base: str) -> list[dict[str, Any]]:
    """Read the raw ladder rows for one (measure, ref_month) as dicts.

    Reconstructs ``implied_prob = (yes_bid + yes_ask) / 2`` on read (never
    persisted upstream). Returns ``[]`` when the partition is absent.
    """
    import pyarrow.dataset as ds  # lazy

    measure_path = f"{bucket_base}/measure={measure}"
    try:
        dataset = ds.dataset(measure_path, format="parquet", partitioning="hive")
    except FileNotFoundError:
        return []
    rows = dataset.to_table().to_pylist()
    ladders: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("ref_month")) != str(ref_month):
            continue
        strike = row.get("strike")
        yes_bid = row.get("yes_bid")
        yes_ask = row.get("yes_ask")
        if strike is None or yes_bid is None or yes_ask is None:
            continue
        ladders.append(
            {
                "strike": float(strike),
                "implied_prob": (float(yes_bid) + float(yes_ask)) / 2.0,
            }
        )
    return ladders


def read_sources(
    measures: Sequence[str],
    gh_fit_bucket: str = GH_FIT_BUCKET,
    raw_bucket: str = RAW_BUCKET,
) -> dict[str, Any]:
    """Read GH fits + raw ladders for every measure behind the mockable boundary.

    Returns ``{"gh_fit": {measure: [rows...]}, "ladders": {(measure, ref_month,
    as_of): [points...]}}``. Tests replace this whole function with a fixture so
    pyarrow/GCS are never exercised offline.
    """
    gh_fit: dict[str, list[dict[str, Any]]] = {}
    ladders: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for measure in measures:
        rows = _read_gh_fit(measure, gh_fit_bucket)
        gh_fit[measure] = rows
        for row in rows:
            ref_month = str(row.get("ref_month", ""))
            as_of = _as_of_date(row)
            key = (measure, ref_month, as_of)
            if ref_month and key not in ladders:
                ladders[key] = _read_raw_ladders(measure, ref_month, as_of, raw_bucket)
    return {"gh_fit": gh_fit, "ladders": ladders}


# ---------------------------------------------------------------------------
# Pure transform: sources -> public JSON payload (the tested path).
# ---------------------------------------------------------------------------

def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_of_date(row: Mapping[str, Any]) -> str:
    raw = row.get("as_of_ts") or ""
    return str(raw)[:10]


def _latest_fit_per_ref_month(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep the single most recent fit row per reference month for a measure.

    Each row is one market; a (measure, ref_month) has one fitted distribution
    per as_of. We select the latest as_of per ref_month, then (defensively) the
    first finite-parameter row for that as_of.
    """
    best: dict[str, dict[str, Any]] = {}
    for row in rows:
        ref_month = str(row.get("ref_month", ""))
        if not ref_month:
            continue
        as_of = str(row.get("as_of_ts", ""))
        current = best.get(ref_month)
        if current is None or as_of > str(current.get("as_of_ts", "")):
            best[ref_month] = dict(row)
    return [best[ref_month] for ref_month in sorted(best)]


def _build_measure_entry(
    measure: str,
    fit: Mapping[str, Any],
    ladder_points: Sequence[Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Build one public measure entry, or ``None`` if the fit is unusable."""
    mu = _finite(fit.get("mu"))
    b = _finite(fit.get("b"))
    g = _finite(fit.get("g"))
    h = _finite(fit.get("h"))
    if None in (mu, b, g, h):
        return None

    points: list[dict[str, float]] = []
    strikes: list[float] = []
    for row in ladder_points:
        strike = _finite(row.get("strike"))
        prob = _finite(row.get("implied_prob"))
        if strike is None or prob is None:
            continue
        points.append({"strike": strike, "implied_prob": max(0.0, min(1.0, prob))})
        strikes.append(strike)
    points.sort(key=lambda item: item["strike"])

    implied_mean = _finite(fit.get("implied_mean"))
    implied_median = _finite(fit.get("implied_median"))

    # Strike axis: prefer the observed ladder span; otherwise centre on the mean.
    if strikes:
        strike_min, strike_max = min(strikes), max(strikes)
        if strike_min == strike_max:
            strike_min -= 0.5
            strike_max += 0.5
    else:
        centre = implied_mean if implied_mean is not None else mu
        strike_min, strike_max = centre - 2.0, centre + 2.0

    try:
        curve = _reconstruct_curve(
            {"mu": mu, "b": b, "g": g, "h": h, "c": fit.get("c", 0.0), "q": fit.get("q", 0.0)},
            strike_min,
            strike_max,
        )
    except Exception as exc:  # reconstruction is best-effort; emit text-only entry
        print(f"[CRITICAL] curve reconstruction failed for measure={measure}: {exc}")
        curve = {"x": [], "cdf": [], "pdf": []}

    return {
        "measure": measure,
        "reference_month": str(fit.get("ref_month", "")),
        "as_of": _as_of_date(fit),
        "axis_unit": str(fit.get("axis_unit", "")),
        "implied_mean": implied_mean,
        "implied_median": implied_median,
        # NOTE: the fitted-distribution parameter count (fit["n_params"]) is
        # deliberately NOT emitted — the fitting method is confidential and must
        # not be inferable from the public JSON.
        "n_strikes": int(fit.get("n_strikes", len(points)) or len(points)),
        "repaired": bool(fit.get("repaired", False)),
        "prob_mad_err": _finite(fit.get("prob_mad_err")),
        "curve": curve,
        "market_points": points,
    }


def build_payload(
    sources: Mapping[str, Any],
    measures: Sequence[str] = MEASURES,
    *,
    generated_at_utc: Optional[str] = None,
) -> dict[str, Any]:
    """Transform read sources into the public JSON payload (pure, testable)."""
    gh_fit = sources.get("gh_fit", {}) or {}
    ladders = sources.get("ladders", {}) or {}

    entries: list[dict[str, Any]] = []
    missing: list[str] = []
    latest_as_of = ""

    for measure in measures:
        rows = gh_fit.get(measure) or []
        fits = _latest_fit_per_ref_month(rows)
        if not fits:
            missing.append(measure)
            continue
        fit = fits[-1]  # latest reference month available for this measure
        as_of = _as_of_date(fit)
        ladder_points = ladders.get((measure, str(fit.get("ref_month", "")), as_of), [])
        entry = _build_measure_entry(measure, fit, ladder_points)
        if entry is None:
            missing.append(measure)
            continue
        latest_as_of = max(latest_as_of, entry["as_of"])
        entries.append(entry)

    warning = None
    if missing:
        warning = "Measures unavailable: " + ", ".join(sorted(missing))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at_utc or _now_utc(),
        "latest_as_of": latest_as_of or None,
        "model_version": MODEL_VERSION,
        "warning": warning,
        "measures": entries,
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stable_generated_at(previous: Optional[Mapping[str, Any]], payload: Mapping[str, Any]) -> str:
    """Reuse the previous timestamp when the content is otherwise unchanged."""
    if not previous:
        return payload["generated_at_utc"]
    comparable_keys = [key for key in payload if key != "generated_at_utc"]
    if all(previous.get(key) == payload[key] for key in comparable_keys) and set(
        previous
    ) - {"generated_at_utc"} == set(comparable_keys):
        stored = previous.get("generated_at_utc")
        if isinstance(stored, str) and stored:
            return stored
    return payload["generated_at_utc"]


def publish(output_path: Path, sources: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Read sources (unless supplied), build the payload, write stable JSON."""
    if sources is None:
        sources = read_sources(MEASURES)
    payload = build_payload(sources)

    previous = None
    if output_path.exists():
        try:
            previous = json.loads(output_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None
    payload["generated_at_utc"] = _stable_generated_at(previous, payload)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/cpi_prediction_markets.json", type=Path)
    parser.add_argument("--gh-fit-bucket", default=GH_FIT_BUCKET)
    parser.add_argument("--raw-bucket", default=RAW_BUCKET)
    args = parser.parse_args()
    sources = read_sources(MEASURES, gh_fit_bucket=args.gh_fit_bucket, raw_bucket=args.raw_bucket)
    payload = publish(args.output, sources=sources)
    print(
        f"Wrote {args.output}: measures={len(payload['measures'])} "
        f"latest_as_of={payload['latest_as_of']} warning={payload['warning']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

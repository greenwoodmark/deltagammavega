"""Derived GCS cache for daily TIP/TLT cross-shape GH5 premiums."""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.fs as pafs
import pyarrow.parquet as pq

TRADING_ROOT = Path("/home/mark/trading_env")
if str(TRADING_ROOT / "gs_marquee") not in os.sys.path:
    os.sys.path.insert(0, str(TRADING_ROOT / "gs_marquee"))

from infrastructure.equity_option_payoffs import construct_delta_option  # noqa: E402

CACHE_BASE = "gs://systematicpositiveskew/tip_tlt_cache/cross_shape_premiums"
CACHE_SCHEMA_VERSION = "tip_tlt_cross_shape_premium_cache_v1"
PRICING_VERSION = "gh5_cross_shape_premium_v1_percentile_seed_solver"
TENOR_YEARS = 1.0 / 12.0
PUT_DELTAS = (0.05, 0.15, 0.25, 0.40)
CALL_DELTAS = (0.40, 0.25, 0.15, 0.05)
CACHE_COLUMNS = (
    "date",
    "base_symbol",
    "shape_symbol",
    "right",
    "target_delta",
    "premium",
    "base_forward",
    "model_version",
    "objective_name",
    "tip_settings_hash",
    "tlt_settings_hash",
    "pricing_version",
    "tenor",
    "fit_fingerprint_tip",
    "fit_fingerprint_tlt",
)
CACHE_SCHEMA = pa.schema([
    pa.field("date", pa.large_string(), nullable=False),
    pa.field("base_symbol", pa.large_string(), nullable=False),
    pa.field("shape_symbol", pa.large_string(), nullable=False),
    pa.field("right", pa.large_string(), nullable=False),
    pa.field("target_delta", pa.float64(), nullable=False),
    pa.field("premium", pa.float64(), nullable=True),
    pa.field("base_forward", pa.float64(), nullable=False),
    pa.field("model_version", pa.large_string(), nullable=False),
    pa.field("objective_name", pa.large_string(), nullable=False),
    pa.field("tip_settings_hash", pa.large_string(), nullable=False),
    pa.field("tlt_settings_hash", pa.large_string(), nullable=False),
    pa.field("pricing_version", pa.large_string(), nullable=False),
    pa.field("tenor", pa.float64(), nullable=False),
    pa.field("fit_fingerprint_tip", pa.large_string(), nullable=False),
    pa.field("fit_fingerprint_tlt", pa.large_string(), nullable=False),
])


def cache_date_path(cache_base: str, date: str) -> str:
    """Return the per-date cache Parquet path."""
    return posixpath.join(
        cache_base.rstrip("/"),
        f"year={date[:4]}",
        f"month={date[5:7]}",
        f"day={date[8:10]}",
        f"{date}.parquet",
    )


def _filesystem_for(uri: str) -> pafs.FileSystem:
    return pafs.GcsFileSystem() if uri.startswith("gs://") else pafs.LocalFileSystem()


def _object_path(uri: str) -> str:
    return uri[5:] if uri.startswith("gs://") else uri


def _fit_value(value) -> str | float | int | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (np.floating, float)):
        return float(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    return str(value)


def fit_fingerprint(fit: pd.Series) -> str:
    """Hash the source fields that determine a cached premium."""
    fields = (
        "date", "model_version", "objective_name", "settings_hash",
        "b", "g", "h", "c", "q", "fwd", "truncpoint", "zsteps",
    )
    payload = {field: _fit_value(fit.get(field)) for field in fields}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cache_frame(rows: Iterable[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(list(rows), columns=CACHE_COLUMNS)
    if frame.empty:
        return pd.DataFrame(columns=CACHE_COLUMNS)
    for column in ("date", "base_symbol", "shape_symbol", "right", "model_version", "objective_name", "tip_settings_hash", "tlt_settings_hash", "pricing_version", "fit_fingerprint_tip", "fit_fingerprint_tlt"):
        frame[column] = frame[column].fillna("").astype(str)
    for column in ("target_delta", "premium", "base_forward", "tenor"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return frame[list(CACHE_COLUMNS)]


def build_date_rows(date: str, tip_fit: pd.Series, tlt_fit: pd.Series) -> pd.DataFrame:
    """Build the 16 native-scale/cross-shape premium rows for one paired date."""
    fits = {"TIP": tip_fit, "TLT": tlt_fit}
    fingerprints = {symbol: fit_fingerprint(fit) for symbol, fit in fits.items()}
    rows: list[dict] = []
    for base_symbol, shape_symbol in (("TIP", "TLT"), ("TLT", "TIP")):
        base_fit = fits[base_symbol]
        shape_fit = fits[shape_symbol]
        mixed_fit = base_fit.copy()
        for parameter in ("g", "h", "c", "q"):
            mixed_fit[parameter] = shape_fit[parameter]
        for right, deltas in (("P", PUT_DELTAS), ("C", CALL_DELTAS)):
            for absolute_delta in deltas:
                signed_delta = -absolute_delta if right == "P" else absolute_delta
                premium: float | None
                try:
                    option = construct_delta_option(
                        mixed_fit,
                        right=right,
                        target_delta=signed_delta,
                        tenor_years=TENOR_YEARS,
                    )
                    premium = float(option.premium)
                except (ValueError, FloatingPointError):
                    premium = None
                rows.append({
                    "date": date,
                    "base_symbol": base_symbol,
                    "shape_symbol": shape_symbol,
                    "right": right,
                    "target_delta": absolute_delta,
                    "premium": premium,
                    "base_forward": float(base_fit["fwd"]),
                    "model_version": str(base_fit["model_version"]),
                    "objective_name": str(base_fit.get("objective_name", "")),
                    "tip_settings_hash": str(tip_fit.get("settings_hash", "")),
                    "tlt_settings_hash": str(tlt_fit.get("settings_hash", "")),
                    "pricing_version": PRICING_VERSION,
                    "tenor": TENOR_YEARS,
                    "fit_fingerprint_tip": fingerprints["TIP"],
                    "fit_fingerprint_tlt": fingerprints["TLT"],
                })
    return _cache_frame(rows)


def write_date_cache(frame: pd.DataFrame, date: str, cache_base: str = CACHE_BASE) -> str:
    """Write or replace one compact date file using Snappy Parquet."""
    frame = _cache_frame(frame.to_dict("records"))
    if len(frame) != 16:
        raise ValueError(f"cache date {date} must contain 16 rows, got {len(frame)}")
    target = cache_date_path(cache_base, date)
    filesystem = _filesystem_for(cache_base)
    if not cache_base.startswith("gs://"):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(frame, schema=CACHE_SCHEMA, preserve_index=False, safe=True)
    pq.write_table(table, _object_path(target), filesystem=filesystem, compression="snappy")
    return target


def read_date_cache(date: str, cache_base: str = CACHE_BASE) -> pd.DataFrame:
    """Read one date file, returning an empty frame when it is absent."""
    target = cache_date_path(cache_base, date)
    filesystem = _filesystem_for(cache_base)
    try:
        table = pq.read_table(_object_path(target), filesystem=filesystem)
    except (FileNotFoundError, OSError, pa.ArrowInvalid):
        return pd.DataFrame(columns=CACHE_COLUMNS)
    return table.to_pandas()[list(CACHE_COLUMNS)]


def cache_date_is_current(existing: pd.DataFrame, expected: pd.DataFrame) -> bool:
    """Check whether an existing date file matches current source fingerprints."""
    if len(existing) != 16 or len(expected) != 16:
        return False
    key_columns = ("base_symbol", "shape_symbol", "right", "target_delta")
    left = existing.sort_values(list(key_columns)).reset_index(drop=True)
    right = expected.sort_values(list(key_columns)).reset_index(drop=True)
    if not left[list(key_columns)].equals(right[list(key_columns)]):
        return False
    for column in (
        "date", "base_forward", "model_version", "objective_name",
        "tip_settings_hash", "tlt_settings_hash", "pricing_version",
        "tenor", "fit_fingerprint_tip", "fit_fingerprint_tlt",
    ):
        if not left[column].equals(right[column]):
            return False
    return True


def read_cached_adjusted_history(
    base_symbol: str,
    shape_symbol: str,
    right: str,
    target_deltas: tuple[float, ...],
    start_date: str,
    end_date_exclusive: str,
    allowed_dates: set[str] | None = None,
    cache_base: str = CACHE_BASE,
) -> dict[float, list[float]]:
    """Read finite cached premiums for the current paired three-year window."""
    history = {float(delta): [] for delta in target_deltas}
    filesystem = _filesystem_for(cache_base)
    root = _object_path(cache_base)
    try:
        dataset = ds.dataset(root, filesystem=filesystem, format="parquet", partitioning="hive", ignore_prefixes=[".", "_"])
        filters = (
            (ds.field("date") >= start_date)
            & (ds.field("date") < end_date_exclusive)
            & (ds.field("base_symbol") == base_symbol)
            & (ds.field("shape_symbol") == shape_symbol)
            & (ds.field("right") == right)
        )
        frame = dataset.to_table(filter=filters, columns=["date", "target_delta", "premium"]).to_pandas()
    except (FileNotFoundError, OSError, pa.ArrowInvalid, pa.ArrowNotImplemented):
        return history
    if frame.empty:
        return history
    frame["date"] = frame["date"].astype(str)
    if allowed_dates is not None:
        frame = frame.loc[frame["date"].isin(allowed_dates)]
    frame["target_delta"] = pd.to_numeric(frame["target_delta"], errors="coerce")
    frame["premium"] = pd.to_numeric(frame["premium"], errors="coerce")
    for delta in target_deltas:
        values = frame.loc[frame["target_delta"].eq(float(delta)), "premium"]
        history[float(delta)] = values.loc[np.isfinite(values)].astype(float).tolist()
    return history


def update_cache_from_storage(
    *,
    cache_base: str = CACHE_BASE,
    start_date: str | None = None,
    end_date: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Idempotently backfill or update all paired GH5 fit dates."""
    try:
        from generate_tip_tlt_model_data import (
            GH5_VERSION,
            SYMBOLS,
            _normalize_percentile_fit_frame,
            _read_fit_frame,
        )
    except ModuleNotFoundError:  # pragma: no cover - package-style invocation.
        from tools.generate_tip_tlt_model_data import (
            GH5_VERSION,
            SYMBOLS,
            _normalize_percentile_fit_frame,
            _read_fit_frame,
        )

    raw_frames = {symbol: _read_fit_frame(symbol, GH5_VERSION) for symbol in SYMBOLS}
    latest_fits = {}
    normalized = {}
    for symbol in SYMBOLS:
        raw = raw_frames[symbol]
        if raw.empty:
            raise RuntimeError(f"No GH5 fits found for {symbol}")
        raw = raw.copy()
        raw["date"] = pd.to_datetime(raw["date"], errors="raise").dt.strftime("%Y-%m-%d")
        latest_date = raw["date"].max()
        candidates = raw.loc[raw["date"].eq(latest_date)].copy()
        if "fit_datetime" in candidates.columns:
            candidates = candidates.sort_values("fit_datetime")
        latest_fits[symbol] = candidates.iloc[-1]
        normalized[symbol] = _normalize_percentile_fit_frame(raw, latest_fits[symbol])
    paired_dates = sorted(set(normalized[SYMBOLS[0]]["date"]).intersection(normalized[SYMBOLS[1]]["date"]))
    if start_date is not None:
        paired_dates = [date for date in paired_dates if date >= start_date]
    if end_date is not None:
        paired_dates = [date for date in paired_dates if date <= end_date]
    by_date = {
        symbol: {str(row["date"]): row for _, row in normalized[symbol].iterrows()}
        for symbol in SYMBOLS
    }
    report = {"processed": 0, "written": 0, "skipped": 0, "recomputed": 0, "dates": [], "dry_run": dry_run}
    for date in paired_dates:
        expected = build_date_rows(date, by_date["TIP"][date], by_date["TLT"][date])
        existing = read_date_cache(date, cache_base)
        report["processed"] += 1
        if cache_date_is_current(existing, expected):
            report["skipped"] += 1
            status = "skipped"
        else:
            report["recomputed"] += int(not existing.empty)
            if not dry_run:
                write_date_cache(expected, date, cache_base)
            report["written"] += 1
            status = "would_write" if dry_run else ("recomputed" if not existing.empty else "written")
        report["dates"].append({"date": date, "status": status, "rows": len(expected)})
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-base", default=CACHE_BASE)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(update_cache_from_storage(
        cache_base=args.cache_base,
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=args.dry_run,
    ))

#!/usr/bin/env python3
"""Generate the derived Jupiter performance-fee backtest payload."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
from google.cloud import storage

TRADING_ROOT = Path(os.environ.get("TRADING_ENV_ROOT", "/home/mark/trading_env"))
if str(TRADING_ROOT / "models/JUP") not in sys.path:
    sys.path.insert(0, str(TRADING_ROOT / "models/JUP"))

from jupiter_valuation.performance_fee_payload import build_backtest_payload  # noqa: E402

DEFAULT_BUCKET = "systematicpositiveskew"
DEFAULT_ROOT = "fund_data/jupiter"
GEAR_NAV_ISIN = "IE00BLP5S809"
GEAR_FUND_ID = "JAM_GEAR_S"
OUTPUT_NAME = "jup_performance_fee.json"


def _load_successful_ingestion_log(
    client: storage.Client,
    bucket_name: str,
    root: str,
    *,
    require_run_date: str | None = None,
) -> tuple[str, dict[str, Any]]:
    prefix = f"{root.strip('/')}/ingestion_log/"
    blobs = sorted(client.list_blobs(bucket_name, prefix=prefix), key=lambda blob: blob.name)
    if not blobs:
        raise RuntimeError("No Jupiter ingestion log is available")
    for blob in reversed(blobs):
        try:
            payload = json.loads(blob.download_as_bytes().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid Jupiter ingestion log: {blob.name}") from exc
        if payload.get("status") == "success" and (
            require_run_date is None or payload.get("run_date") == require_run_date
        ):
            return f"gs://{bucket_name}/{blob.name}", payload
    expected = f" for run_date={require_run_date}" if require_run_date else ""
    raise RuntimeError(f"No successful Jupiter ingestion log is available{expected}")


def _load_gear_nav_rows(client: storage.Client, bucket_name: str, root: str) -> list[dict[str, Any]]:
    uri = f"gs://{bucket_name}/{root.strip('/')}/nav/isin={GEAR_NAV_ISIN}"
    try:
        dataset = ds.dataset(
            uri,
            format="parquet",
            partitioning="hive",
            ignore_prefixes=[".", "_"],
            exclude_invalid_files=True,
        )
        rows = dataset.to_table().to_pylist()
    except (FileNotFoundError, OSError, ValueError, RuntimeError) as exc:
        raise RuntimeError(f"Unable to read canonical GEAR NAV data from {uri}") from exc
    if not rows:
        raise RuntimeError("Canonical GEAR NAV data is empty")
    return rows


def _load_latest_gear_fund_size_gbp_m(
    client: storage.Client,
    bucket_name: str,
    root: str,
) -> tuple[float, date, str] | None:
    """Return the latest live GEAR fund-centre size as (GBP-millions, as_of_date, provenance).

    Reads the hive-partitioned fund_size dataset and selects the GEAR fund-level
    (scope='fund') GBP row with the maximum as_of_date. No FX is applied: if the
    row's currency is not GBP the value is treated as unavailable. The stored
    fund_size_value is in GBP; this converts it to GBP MILLIONS (10.27 B -> 10_270.0)
    on read and never persists the derived column. Returns None (non-fatal) when the
    dataset is missing/unreadable or no GEAR GBP fund-level row exists, so the payload
    falls back to the interpolated historical anchor.
    """
    uri = f"gs://{bucket_name}/{root.strip('/')}/fund_size/"
    try:
        dataset = ds.dataset(
            uri,
            format="parquet",
            partitioning="hive",
            ignore_prefixes=[".", "_"],
            exclude_invalid_files=True,
        )
        rows = dataset.to_table().to_pylist()
    except (FileNotFoundError, OSError, ValueError, RuntimeError):
        return None
    candidates = [
        row
        for row in rows
        if row.get("fund_id") == GEAR_FUND_ID
        and row.get("scope") == "fund"
        and row.get("currency") == "GBP"
    ]
    if not candidates:
        return None
    latest = max(candidates, key=lambda row: row["as_of_date"])
    as_of_value = latest["as_of_date"]
    as_of = as_of_value if isinstance(as_of_value, date) else date.fromisoformat(str(as_of_value))
    unit = str(latest["fund_size_unit"]).upper()
    scale = {"B": 1e9, "M": 1e6, "K": 1e3}.get(unit)
    if scale is None:
        return None
    # Input value is GBP; output is GBP MILLIONS (no FX because currency is GBP).
    aum_gbp_m = float(latest["fund_size_value"]) * scale / 1e6
    provenance = f"live_fund_size {GEAR_FUND_ID} GBP {as_of.isoformat()}"
    return aum_gbp_m, as_of, provenance


def generate_payload(
    *,
    bucket_name: str = DEFAULT_BUCKET,
    root: str = DEFAULT_ROOT,
    client: storage.Client | None = None,
    generated_at_utc: datetime | None = None,
    require_run_date: str | None = None,
) -> dict[str, Any]:
    gcs = client or storage.Client()
    ingestion_log_uri, ingestion_summary = _load_successful_ingestion_log(
        gcs,
        bucket_name,
        root,
        require_run_date=require_run_date,
    )
    nav_rows = _load_gear_nav_rows(gcs, bucket_name, root)
    generated_at_utc = generated_at_utc or datetime.now(timezone.utc)
    live_fund_size = _load_latest_gear_fund_size_gbp_m(gcs, bucket_name, root)
    scenario_kwargs: dict[str, Any] = {}
    if live_fund_size is not None:
        scenario_aum_gbp_m, scenario_aum_as_of, scenario_aum_provenance = live_fund_size
        scenario_kwargs = {
            "scenario_aum_gbp_m": scenario_aum_gbp_m,
            "scenario_aum_as_of": scenario_aum_as_of,
            "scenario_aum_provenance": scenario_aum_provenance,
        }
    payload = build_backtest_payload(
        nav_rows,
        generated_at_utc=generated_at_utc,
        source_ingestion_log=ingestion_log_uri,
        **scenario_kwargs,
    )
    payload["source_ingestion_run_id"] = ingestion_summary.get("run_id") or ingestion_log_uri.rsplit("/", 1)[-1].removesuffix(".json")
    payload["source_ingestion_run_date"] = ingestion_summary.get("run_date")
    payload["source_latest_nav"] = ingestion_summary.get("latest_nav")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=os.environ.get("JUPITER_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--root", default=os.environ.get("JUPITER_ROOT", DEFAULT_ROOT))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("JUPITER_PERFORMANCE_FEE_OUTPUT", "/home/mark/deltagammavega/data/jup_performance_fee.json")),
    )
    parser.add_argument(
        "--require-run-date",
        help="require a successful ingestion log for this UTC run date before generating output",
    )
    args = parser.parse_args(argv)
    payload = generate_payload(
        bucket_name=args.bucket,
        root=args.root,
        require_run_date=args.require_run_date,
    )
    atomic_write_json(args.output, payload)
    print(
        f"wrote {args.output} ({len(payload['periods'])} periods, "
        f"NAV through {payload['source_nav_end_date']}, "
        f"ingestion={payload['source_ingestion_log']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

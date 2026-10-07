import sys
from pathlib import Path

import pytest

TOOLS = Path("/home/mark/deltagammavega/tools")
sys.path.insert(0, str(TOOLS))

from datetime import date  # noqa: E402

import generate_jup_performance_fee_data as gen  # noqa: E402
from generate_jup_performance_fee_data import (  # noqa: E402
    _load_latest_gear_fund_size_gbp_m,
    _load_successful_ingestion_log,
)


class FakeBlob:
    def __init__(self, name, payload):
        self.name = name
        self._payload = payload

    def download_as_bytes(self):
        return self._payload


class FakeClient:
    def __init__(self, blobs):
        self.blobs = blobs

    def list_blobs(self, bucket_name, prefix):
        return self.blobs


def test_ingestion_gate_requires_successful_expected_run_date():
    client = FakeClient([
        FakeBlob("fund_data/jupiter/ingestion_log/old.json", b'{"status":"success","run_date":"2026-09-12"}'),
        FakeBlob("fund_data/jupiter/ingestion_log/new.json", b'{"status":"success","run_date":"2026-09-13"}'),
    ])
    uri, summary = _load_successful_ingestion_log(
        client,
        "bucket",
        "fund_data/jupiter",
        require_run_date="2026-09-13",
    )
    assert uri.endswith("new.json")
    assert summary["run_date"] == "2026-09-13"


def test_ingestion_gate_rejects_missing_expected_success():
    client = FakeClient([
        FakeBlob("fund_data/jupiter/ingestion_log/old.json", b'{"status":"success","run_date":"2026-09-12"}'),
    ])
    with pytest.raises(RuntimeError, match="run_date=2026-09-13"):
        _load_successful_ingestion_log(
            client,
            "bucket",
            "fund_data/jupiter",
            require_run_date="2026-09-13",
        )


class FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def to_pylist(self):
        return self._rows


class FakeDataset:
    def __init__(self, rows):
        self._rows = rows

    def to_table(self):
        return FakeTable(self._rows)


def test_load_latest_gear_fund_size_picks_max_date_gbp_fund_row(monkeypatch):
    rows = [
        {"fund_id": "JAM_GEAR_S", "as_of_date": date(2026, 9, 3), "currency": "GBP",
         "fund_size_value": 10.20, "fund_size_unit": "B", "scope": "fund"},
        {"fund_id": "JAM_GEAR_S", "as_of_date": date(2026, 9, 4), "currency": "GBP",
         "fund_size_value": 10.27, "fund_size_unit": "B", "scope": "fund"},
        # non-GEAR fund (ignored)
        {"fund_id": "JAM_OTHER", "as_of_date": date(2026, 9, 5), "currency": "GBP",
         "fund_size_value": 99.0, "fund_size_unit": "B", "scope": "fund"},
        # GEAR but non-GBP (ignored, no FX)
        {"fund_id": "JAM_GEAR_S", "as_of_date": date(2026, 9, 5), "currency": "USD",
         "fund_size_value": 13.61, "fund_size_unit": "B", "scope": "fund"},
    ]
    monkeypatch.setattr(gen.ds, "dataset", lambda *a, **k: FakeDataset(rows))

    result = _load_latest_gear_fund_size_gbp_m(object(), "bucket", "fund_data/jupiter")

    assert result is not None
    aum_gbp_m, as_of, provenance = result
    assert aum_gbp_m == pytest.approx(10_270.0)
    assert as_of == date(2026, 9, 4)
    assert "live_fund_size" in provenance


def test_load_latest_gear_fund_size_returns_none_when_no_gbp_gear_row(monkeypatch):
    rows = [
        {"fund_id": "JAM_GEAR_S", "as_of_date": date(2026, 9, 4), "currency": "USD",
         "fund_size_value": 13.61, "fund_size_unit": "B", "scope": "fund"},
        {"fund_id": "JAM_OTHER", "as_of_date": date(2026, 9, 4), "currency": "GBP",
         "fund_size_value": 5.0, "fund_size_unit": "B", "scope": "fund"},
    ]
    monkeypatch.setattr(gen.ds, "dataset", lambda *a, **k: FakeDataset(rows))

    assert _load_latest_gear_fund_size_gbp_m(object(), "bucket", "fund_data/jupiter") is None


def test_load_latest_gear_fund_size_returns_none_on_read_error(monkeypatch):
    def _raise(*a, **k):
        raise FileNotFoundError("no dataset")

    monkeypatch.setattr(gen.ds, "dataset", _raise)

    assert _load_latest_gear_fund_size_gbp_m(object(), "bucket", "fund_data/jupiter") is None


def test_jup_page_declares_dynamic_backtest_and_scenario_contract():
    page = Path("/home/mark/deltagammavega/site/shared/JUP/model.html").read_text(encoding="utf-8")
    assert 'id="jup-pf-backtest-body"' in page
    assert 'id="jup-pf-scenario-body"' in page
    assert 'id="jup-gear-regression-interpretation"' in page
    assert "jup_performance_fee.json" in page
    assert "renderPerformanceFeeBacktest" in page
    assert "renderFy2026Scenarios" in page
    assert "renderPerformanceFeePayload" in page
    assert "renderJupGearRegressionInterpretation" in page
    assert "Fair value for" in page
    assert "based on NAV performance" in page
    assert "jup_gear_chart.json" in page
    assert "trailing_pe" in page
    assert "JUP trailing P/E ratio" in page
    assert "ISF trailing P/E ratio" in page
    assert "UKX trailing P/E ratio" not in page
    assert "price_quoted" in page
    assert "eps_pence" in page
    assert "A. Performance-fee EPS model assumptions" in page
    assert "Reported consolidated performance-fee result versus basic fund-level estimate" not in page
    assert 'id="pf-eps-note"' not in page
    for label in ("GEAR contractual fee", "FY2025 calibration yield", "UK Dynamic Long Short AUM"):
        assert label in page

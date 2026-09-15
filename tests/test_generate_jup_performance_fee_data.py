import sys
from pathlib import Path

import pytest

TOOLS = Path("/home/mark/deltagammavega/tools")
sys.path.insert(0, str(TOOLS))

from generate_jup_performance_fee_data import _load_successful_ingestion_log  # noqa: E402


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

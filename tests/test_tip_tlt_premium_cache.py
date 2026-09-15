import pandas as pd

from tools.tip_tlt_premium_cache import (
    build_date_rows,
    cache_date_is_current,
    read_cached_adjusted_history,
    read_date_cache,
    write_date_cache,
)


def _fit(fwd: float, *, b: float = 0.15, g: float = -0.08) -> pd.Series:
    return pd.Series({
        "date": "2026-01-02",
        "model_version": "gh5_v1",
        "objective_name": "synthetic_black76_iv_l2_v1",
        "settings_hash": "settings-v1",
        "fwd": fwd,
        "b": b,
        "g": g,
        "h": 0.04,
        "c": 0.006,
        "q": -0.004,
        "truncpoint": 4.5,
        "zsteps": 180,
        "fit_datetime": "2026-01-02 12:00:00+00:00",
    })


def test_build_date_rows_has_compact_sixteen_row_schema():
    rows = build_date_rows("2026-01-02", _fit(100.0), _fit(110.0, g=0.12))

    assert len(rows) == 16
    assert set(rows["right"]) == {"P", "C"}
    assert set(zip(rows["base_symbol"], rows["shape_symbol"])) == {("TIP", "TLT"), ("TLT", "TIP")}
    assert set(rows.columns) == {
        "date", "base_symbol", "shape_symbol", "right", "target_delta", "premium",
        "base_forward", "model_version", "objective_name", "tip_settings_hash",
        "tlt_settings_hash", "pricing_version", "tenor", "fit_fingerprint_tip",
        "fit_fingerprint_tlt",
    }


def test_date_cache_is_idempotent_and_detects_source_fit_correction(tmp_path):
    tip = _fit(100.0)
    tlt = _fit(110.0, g=0.12)
    expected = build_date_rows("2026-01-02", tip, tlt)
    write_date_cache(expected, "2026-01-02", str(tmp_path))
    existing = read_date_cache("2026-01-02", str(tmp_path))

    assert cache_date_is_current(existing, expected)
    corrected = build_date_rows("2026-01-02", tip, _fit(110.0, g=0.20))
    assert not cache_date_is_current(existing, corrected)


def test_stale_dates_remain_readable_but_allowed_dates_filter_them(tmp_path):
    tip = _fit(100.0)
    tlt = _fit(110.0, g=0.12)
    first = build_date_rows("2026-01-02", tip, tlt)
    second = build_date_rows("2026-01-03", tip, tlt)
    write_date_cache(first, "2026-01-02", str(tmp_path))
    write_date_cache(second, "2026-01-03", str(tmp_path))

    assert len(read_date_cache("2026-01-02", str(tmp_path))) == 16
    history = read_cached_adjusted_history(
        "TIP", "TLT", "P", (0.05, 0.15, 0.25, 0.40),
        "2026-01-01", "2026-01-04", allowed_dates={"2026-01-03"}, cache_base=str(tmp_path),
    )
    assert all(len(values) == 1 for values in history.values())

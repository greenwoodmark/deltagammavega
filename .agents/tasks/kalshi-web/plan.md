# Kalshi CPI prediction-markets website page — implementation plan

Branch: `feature/kalshi-prediction-markets-page` (worktree at
`/home/mark/deltagammavega/.worktrees/kalshi-web`). This repo is SEPARATE from
`/home/mark/trading_env`.

## Verified facts about the site build
- Static site. `tools/build_site.py` copies fixed tuples `PUBLIC_FILES`
  (HTML under `site/shared/`) and `PUBLIC_DATA_FILES` (JSON under `data/`) into
  `build/public`. A new page + new data file MUST be added to those tuples.
- `tools/validate_public_build.py` enumerates an ALLOWED_FILES allowlist and a
  REQUIRED_FILES set; both must be updated or the build is rejected / required.
- `deploy_public_site.sh` runs build → validators → firebase deploy. We add our
  validator alongside the others; we DO NOT run firebase deploy.
- `cpurnsa.html` loads Plotly from a CDN (`cdn.plot.ly/plotly-2.35.2.min.js`).
  So the house client-side charting approach is Plotly from CDN — reuse it, do
  not add a new heavy JS dependency.
- `index.html` wordmark: the first "D" is already wrapped in
  `<a class="logo-letter" href="cpurnsa.html" ...>`. The first "e" (x≈164.90)
  is a bare `<text>` in BOTH the nav SVG and the hero SVG (inside
  `<g id="delta-hero">`). We wrap exactly that "e" in both.

## Python environment
- The website repo's REQUIRED path (build_site + validators + the page) is
  stdlib-only / browser-only. System `python3` has no numpy/pandas/pyarrow.
- Tests and the publisher need numpy/pandas/pyarrow; those live in the
  trading_env venvs (`/home/mark/trading_env/venv311`, read-only use of the
  interpreter only — we never modify trading_env). CI uses Python 3.11, so we
  run tests with `venv311`.
- The publisher isolates GCS/pyarrow reading behind a mockable boundary
  (`_read_gh_fit` / `_read_raw_ladders`) so tests use local fixtures with no
  network and no real GCS.

## Source data (trading_env Phase 3, verified)
- GH fit: `gs://.../prediction_markets/kalshi_gh_fit/measure={M}/ref_month={YYYY-MM}/{as_of}.parquet`
  one row per (as_of, market): mu,b,g,h,c,q,n_params, implied_mean,
  implied_median, skew, kurt, medcouple, prob_mad_err, n_strikes, axis_unit,
  repaired, max_abs_adjustment, n_violations, as_of_ts, fit_datetime,
  model_version.
- Raw ladders: `gs://.../prediction_markets/kalshi/measure={M}/ref_month={YYYY-MM}/{as_of}.parquet`
  with strike, yes_bid, yes_ask (implied_prob = (yes_bid+yes_ask)/2 on read).
- Measures: headline_yoy, core_yoy, headline_mom, core_mom.
- GH outcome reconstruction (same math as trading_env `ivmodel`):
  Z grid → X = GCHQrealisation(Z,0,b,g,h,c,q); centre on 0; outcome = mu + X;
  CDF(K) = P(outcome < K); PDF via kernel/weighting over the strike axis.
  The publisher reconstructs a sampled CDF/PDF curve from the stored params
  (lighter than persisting curves in trading_env; the page only plots).

## Files to create / change
1. `site/shared/cpi_prediction_markets.html` — new public page (Plotly CDN,
   dark/house style, nav back to index + cross-link to cpurnsa.html, per-measure
   implied mean/median text fallback, PDF/CDF curves + raw ladder points,
   "as of" + model_version, graceful "data unavailable").
2. `data/cpi_prediction_markets.json` — committed sample/placeholder so the
   build + validator pass before first live publish.
3. `tools/publish_cpi_prediction_markets.py` — argparse, read source → validate
   → emit JSON with stable generated_at_utc, schema_version, warning/health.
4. `tools/validate_cpi_prediction_markets_data.py` — strict schema/array/finite
   validator mirroring validate_softs_diagnostics / validate_uscpi_public_data.
5. `tools/build_site.py` — add page to PUBLIC_FILES, JSON to PUBLIC_DATA_FILES.
6. `tools/validate_public_build.py` — add page + JSON to ALLOWED_FILES.
7. `deploy_public_site.sh` — wire the new validator alongside the others.
8. `site/shared/index.html` — wrap the first "e" in an anchor in BOTH SVGs.
9. `tests/test_publish_cpi_prediction_markets.py`,
   `tests/test_validate_cpi_prediction_markets_data.py`,
   `tests/test_cpi_prediction_markets_build_and_link.py`.

## JSON schema (`cpi_prediction_markets_v1`)
Top-level: schema_version, generated_at_utc, latest_as_of, model_version,
warning, measures[]. Each measure: measure, reference_month, axis_unit,
implied_mean, implied_median, n_params, repaired, prob_mad_err, n_strikes,
curve {x[], cdf[], pdf[]} (equal lengths, finite), market_points[] {strike,
implied_prob}.

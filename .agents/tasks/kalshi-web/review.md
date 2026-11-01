# US CPI prediction-markets implied-distribution page

A new public page renders the Kalshi-implied risk-neutral distribution for US CPI (headline/core, YoY/MoM), fed by a publisher that bridges the trading_env Phase 3 GH-fit GCS parquet into a public-safe JSON, guarded by a strict validator wired into the deploy pipeline. The wordmark's first "e" is hyperlinked to the new page in both the nav and hero SVGs, mirroring the existing "D" anchor. The change is a single commit on `feature/kalshi-prediction-markets-page` (base merge-base `a442c654`), touching only the deltagammavega repo. Everything is pre-live: a committed sample JSON lets the build and all validators pass before the first real publish.

Watch for: nothing blocking. The publisher emits a `warning` field but no separate `health.json` (confirmed) — the task's "health/warning field" requirement is satisfied by `warning`, matching the lighter payload shape this page needs; cpurnsa's `health.json` is produced by its own publisher and is untouched.

**Verdict**: APPROVED

## High-level view

The hyperlink change is exactly scoped. In both `payoffSpectrumNav` and `payoffSpectrumHero`, the first "e" `<text>` (x≈164.90, immediately after the D) is wrapped in `<a class="logo-letter" href="cpi_prediction_markets.html" aria-label="Open CPI prediction markets">` with the `<text>` attributes unchanged, mirroring the D wrapper (href `cpurnsa.html`). Only the D and the first e are logo-letter links in each SVG — confirmed in source and in the built `index.html` (exactly four anchor tags, two per SVG).

The new page follows house style: dark `#071c18` theme, Roboto, the nav/footer idiom, and Plotly from the same CDN version as `cpurnsa.html` (2.35.2), so no new heavy JS dependency enters the site. It is accessible (aria labels, a keyboard-focusable labelled link via the shared `.logo-letter` rule, a visible `dl` text fallback of implied mean/median per measure) and states the "as of" date and model_version. It degrades gracefully: a fetch failure, empty payload, or a missing measure each renders an "unavailable" card rather than breaking.

The publisher mirrors `publish_cpurnsa.py`: argparse, read→build→write, a stable `generated_at_utc` when content is unchanged, a `schema_version`, and a `warning` field. GCS/pyarrow reads sit behind a mockable `read_sources` boundary with lazy `pyarrow`/`numpy`/`scipy` imports, so the repo's required path stays stdlib-only and no heavy Python dependency is added. It treats parquet as untrusted (finite-checks every numeric before emitting) and emits only derived model outputs — no credentials, URIs, or internal fields.

The validator mirrors the strictness of `validate_uscpi_public_data.py` / `validate_softs_diagnostics.py`: rejects non-finite JSON constants, forbidden private fields, wrong schema, missing top-level or per-measure fields, non-finite arrays, mismatched curve lengths, non-monotone x, out-of-range CDF, and negative PDF. It is wired into `deploy_public_site.sh` ahead of `validate_public_build.py`, which still passes. `build_site.py` (PUBLIC_FILES, PUBLIC_DATA_FILES) and `validate_public_build.py` (ALLOWED_FILES) are both updated, and a committed sample JSON ships so the build+validators pass pre-live. No firebase deploy is run by the change. Tests cover the publisher, validator, build-wiring, and the hyperlink. No trading_env files are touched.

<details>
<summary>Issues (0)</summary>

No blocking or actionable concerns.

</details>

<details>
<summary>Details</summary>

### First-"e" anchor in both SVGs

The `index.html` diff wraps the first "e" `<text>` in both SVGs identically to the D. In `payoffSpectrumNav` (the nav wordmark) and `payoffSpectrumHero` (the hero wordmark), the anchor is `<a class="logo-letter" href="cpi_prediction_markets.html" aria-label="Open CPI prediction markets">` around the unchanged `<text x="164.90" y="340.43" font-size="87.4px" transform="rotate(7…, 164.90, 340.43)">e</text>`. The D anchor (href `cpurnsa.html`, aria-label "Open Inflation markets") is unchanged. A grep for `<a class="logo-letter"` returns exactly four anchors across the file — D and e in each SVG — and no other letter (`l`, `t`, `a`, …) is wrapped.

Verified against the built artifact: running `build_site.py --target public` produced `build/public/index.html` with exactly four `logo-letter` anchor tags at the same positions, the first "e" pointing at `cpi_prediction_markets.html`. The built page and `data/cpi_prediction_markets.json` are both present in the build output. The hyperlink test (`test_first_e_links_to_new_page_in_both_svgs`) independently asserts the two-SVG split, that linked letters are exactly `{D, e}` per SVG with the correct hrefs, and that only two anchors exist per SVG — a strong regression guard against a stray letter becoming a link.

### Page accessibility and graceful degradation

The page builds each measure card in JS with an aria-labelled chart (`role="img"` plus an aria-label repeating the implied mean/median), and a `dl.summary` giving the implied mean and median as visible text independent of the chart — so the key figures survive even if Plotly fails to load or a screen reader ignores the SVG. The `.logo-letter` link on the index is keyboard-focusable with a `:focus-visible` style, satisfying the labelled-link requirement.

Three degradation paths exist and each is handled: a non-OK fetch or JSON error renders one "unavailable" card per measure via the `.catch`; an empty `measures` array falls back to the full `MEASURE_ORDER` as unavailable cards; and a measure present in the payload but lacking a chartable curve and points shows a text-only card that still surfaces mean/median. `latest_as_of` null renders "no data yet" rather than throwing.

### Publisher: mockable boundary and stdlib-only required path

`read_sources` is the single seam the tests replace, and `_read_gh_fit` / `_read_raw_ladders` import `pyarrow.dataset` lazily, so importing the module offline pulls in nothing beyond the stdlib. The GH curve is reconstructed publisher-side from stored `(mu, b, g, h, c, q)` params using the additive-location math mirrored from trading_env's ivmodel, with `numpy`/`scipy` imported inside the reconstruction helper — again lazy, so no heavy dependency enters the repo's required path. `_finite` gates every numeric read from parquet, and `_build_measure_entry` returns `None` (counted as a missing measure, surfaced in `warning`) when `mu/b/g/h` are not all finite, so malformed upstream rows degrade to a warning rather than a crash or a poisoned payload.

The emitted schema carries only derived outputs (`implied_mean`, `implied_median`, reconstructed `curve`, `market_points`, fit metadata). No source URI, credential, or local path is written; the validator's forbidden-field scan enforces this at deploy time. `_stable_generated_at` reuses the prior timestamp when every non-timestamp key is byte-equal and the key set matches, giving reproducible output on unchanged content.

### Validator strictness and deploy wiring

`validate_cpi_prediction_markets_data.py` is stdlib-only and refuses `Infinity`/`NaN` via `parse_constant`, scans the raw text for forbidden private field names before parsing, and enforces schema version, the full top-level and per-measure required-field sets, finite-or-null scalars, non-negative integer counts, and a boolean `repaired`. The curve check requires `x`/`cdf`/`pdf` equal length, strictly increasing `x`, CDF within `[0,1]` (± epsilon), and non-negative PDF — matching the publisher's own guarantees so a drift between the two would fail the build. Market points must be exactly `{strike, implied_prob}` with prob in `[0,1]`.

It is wired into `deploy_public_site.sh` between the softs validator and `validate_public_build.py`. Running the data validator against the committed sample reports `measures=4`, and `validate_public_build.py` against the built output reports the public build valid — both pass.

### Build registration and sample data

`build_site.py` adds `cpi_prediction_markets.html` to PUBLIC_FILES and `cpi_prediction_markets.json` to PUBLIC_DATA_FILES; `validate_public_build.py` adds both to ALLOWED_FILES (and so to REQUIRED_FILES via set difference). The committed `data/cpi_prediction_markets.json` is a well-formed four-measure sample (`axis_unit` values "YoY %"/"MoM %" are within the validator's allowed set), which is why the build and validators pass before any live publish. The deploy diff adds only the validator invocation; no `firebase deploy` is introduced.

### Test coverage

Publisher tests cover schema shape, the missing-measure warning, a malformed fit being skipped rather than crashing, empty-source graceful degradation, latest-fit-per-ref-month selection, and both the stable-timestamp and timestamp-moves-on-change paths. Validator tests cover the good payload plus each malformed class: wrong schema, missing top-level field, missing measure field, mismatched curve lengths, non-finite number, non-monotone CDF axis, out-of-range CDF, unknown measure, bad market point, and a forbidden private field. Build-wiring tests confirm the page and data land in `build/public` and that `validate_public_build.validate` accepts the result. The hyperlink test asserts the first-"e" link in both SVGs with the exact-two-anchors guard.

Not tested: the live GCS/parquet read path (`_read_gh_fit`/`_read_raw_ladders`) and the numpy/scipy GH reconstruction are exercised only indirectly — the tests drive the pure emit path with fixtures, by design, since the required repo path is stdlib-only and the heavy math runs on the trading_env box. This is the documented trade-off and is acceptable for this repo.

### Scope

The diff touches only deltagammavega files (`git diff --stat` shows no `trading_env` path). No trading_env file is modified, read into the commit, or otherwise altered. Scope discipline holds.

</details>

<details>
<summary>File map</summary>

- `site/shared/index.html` — wrap first "e" in both nav and hero SVGs in a `logo-letter` anchor to the new page; no other letter changed.
- `site/shared/cpi_prediction_markets.html` — new dark/house-style page; Plotly CDN (2.35.2, no new dep); per-measure text fallback + CDF/PDF curves + ladder points; aria labels; graceful degradation.
- `tools/publish_cpi_prediction_markets.py` — new publisher; mockable GCS boundary, lazy heavy imports, stable timestamp, public-safe schema.
- `tools/validate_cpi_prediction_markets_data.py` — new strict stdlib-only validator.
- `tools/build_site.py` — register new page + data JSON.
- `tools/validate_public_build.py` — allow new page + data JSON.
- `deploy_public_site.sh` — run the new validator before the public-build check.
- `data/cpi_prediction_markets.json` — committed sample so build+validate pass pre-live.
- `tests/test_publish_cpi_prediction_markets.py`, `tests/test_validate_cpi_prediction_markets_data.py`, `tests/test_cpi_prediction_markets_build_and_link.py` — publisher, validator, build-wiring, and hyperlink tests.

Full diff: `git -C /home/mark/deltagammavega/.worktrees/kalshi-web diff a442c654...HEAD`

</details>

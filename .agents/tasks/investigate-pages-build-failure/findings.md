# Findings: GitHub Pages build failure

## Summary answer

The latest Pages run failed during the GitHub-provided **Checkout** step, before Jekyll/site assembly or deployment. The concrete error is:

> `No url found for submodule path '.worktrees/kalshi-cron' in .gitmodules`

The repository tree at `origin/main` records `.worktrees/kalshi-cron` as a mode-160000 Git submodule entry pointing to commit `03bdbed...`, but the repository has no `.gitmodules` file. GitHub's checkout therefore exits 128. This is unrelated to the internal website refresh or to the new softs diagnostic content. The smallest corrective action is to remove the accidental `.worktrees/kalshi-cron` gitlink from the repository index and push that small cleanup commit; do not delete the local worktree unless separately required.

## Evidence

### Failed run and triggering commit

- GitHub run `43232056654`, titled `pages build and deployment`, was created at `2026-11-12T13:56:05Z` for `main` at commit `d6d34c1c6ee78648f7370d6d3ccdf7510a1f7b52`.
- Run metadata identifies it as the dynamic Pages workflow (`path: dynamic/pages/pages-build-deployment`), run number 518, and records conclusion `failure`.
- Build job `131229647731` ran from `13:56:10Z` to `13:56:29Z`. Its steps show `Set up job` and the Jekyll container pull succeeded, `Checkout` failed, and `Build with Jekyll`, `Upload artifact`, and `deploy` were skipped.
- The four check annotations contain the failure message at `.github`, line 94: `No url found for submodule path '.worktrees/kalshi-cron' in .gitmodules`. A related annotation says `/usr/bin/git` exited with code 128. The only other annotation is an informational Ubuntu runner migration notice.
- The triggering commit is `d6d34c1` (`Publish softs diagnostics through 2026-11-12`), authored and committed by Mark Greenwood at `2026-11-12T13:56:03Z`. Its only changed path is `data/softs_diagnostics.json`.

Useful remote evidence links:

- [Failed Pages run](https://github.com/greenwoodmark/deltagammavega/actions/runs/43232056654)
- [Failed build job](https://github.com/greenwoodmark/deltagammavega/actions/runs/43232056654/job/131229647731)
- [Triggering commit](https://github.com/greenwoodmark/deltagammavega/commit/d6d34c1c6ee78648f7370d6d3ccdf7510a1f7b52)

### Repository metadata causing checkout failure

- `git -C /home/mark/deltagammavega ls-tree -l origin/main .worktrees/kalshi-cron` reports:
  `160000 commit 03bdbedb90da096e8aba40ab49393f3242b4296d ... .worktrees/kalshi-cron`.
  Mode `160000` means this is a submodule gitlink, not an ordinary directory.
- `origin/main` contains no `.gitmodules` file. The repository file listing contains `.worktrees/kalshi-cron` but no `.gitmodules`.
- `/home/mark/deltagammavega/.gitignore` ignores `build/`, `site/internal/`, caches, and other local/generated material, but does not ignore `.worktrees/`. This allowed the local worktree path to be staged as a gitlink.
- The local branch is currently one commit behind `origin/main`; the investigation did not alter it. The working tree already had unrelated modifications in generated `data/*.json` files before this investigation.

### Why this is not the internal refresh failure

- The repository workflow `.github/workflows/validate-softs-diagnostics.yml` checks out the website, validates `data/softs_diagnostics.json`, builds the public variant with `python tools/build_site.py --target public`, and validates it with `python tools/validate_public_build.py build/public`.
- For the same triggering SHA, run `43232057271` (`Validate softs diagnostics`) completed successfully. Therefore the refreshed softs artifact passed the repository's validation and public-build checks.
- `tools/build_site.py`, `build_variant()`, and `_assemble_variant()` copy only the approved public HTML/data files into `build/public`; they do not create or resolve Git submodules. `firebase.json` points Firebase Hosting at `build/public`.
- The Pages checkout failed before any Jekyll build. Consequently, the failure cannot be caused by a malformed page, the new softs JSON payload, or the internal website refresh process. It also means no Pages artifact was produced by this run.

## Conclusions

1. The immediate failure is repository structure, not website data: an unconfigured submodule gitlink under `.worktrees/kalshi-cron` prevents GitHub Actions checkout.
2. The triggering softs refresh was accepted by the dedicated validation workflow. The Pages failure happened independently at checkout.
3. The repeated Pages failures on earlier runs are consistent with the same persistent repository metadata problem; the failure is not specific to the `2026-11-09` through `2026-11-11` softs backfill.
4. The local Firebase deployment path documented in `CONTRIBUTING.md` is separate from GitHub Pages. Removing the bad gitlink repairs GitHub checkout, but it does not by itself restart or repair the internal Linux-box refresh/deployment process.

## Recommendation

Make the smallest repository-only fix: remove `.worktrees/kalshi-cron` from the tracked tree/index, while preserving the local worktree directory if it is still needed, then commit and push that cleanup. Do not add a `.gitmodules` entry for this local worktree. After the cleanup reaches `main`, observe the resulting Pages run and confirm that Checkout succeeds, Jekyll/build runs, and an artifact is uploaded. No workflow rerun, deployment, server restart, or code change was performed during this read-only investigation.

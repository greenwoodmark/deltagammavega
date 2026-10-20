# Automated Firebase Hosting deploy for the CPURNSA publish workflow

Adds a Firebase Hosting deploy to `update-cpurnsa-data.yml` so a successful build/validate/commit run publishes `build/public` to live without a human running `deploy_public_site.sh`. This closes the root cause behind the repeated staleness: the pipeline regenerated and committed data but never pushed it to Hosting. The change is a single-file, additive edit (two new steps plus a comment block) appended after the existing commit step. Auth prefers a `FIREBASE_SERVICE_ACCOUNT` key written to a temp credentials file, with a deprecated `FIREBASE_TOKEN` fallback, and fails fast if neither is present.

Watch for: nothing blocking — the deploy is correctly gated as a plain sequential step, runs on both diff and no-diff paths, and hardcodes no project id (confirmed).

**Verdict**: APPROVED

## High-level view

The deploy is the last step in the job, after the four build/validation steps and the `Commit generated public data` step. Because it carries no `if:` condition, a failure in any earlier step aborts the job before deploy is reached, so a validation failure cannot publish. This is the correct fail-closed posture (confirmed).

The no-diff path is handled correctly: the commit step's `exit 0` on "no generated public curve changes" is a success exit, so the job continues to the deploy and re-publishes the freshly reassembled `build/public`. The site stays in sync even on runs with no new data (confirmed).

Auth is service-account-first: `FIREBASE_SERVICE_ACCOUNT` JSON is written to a `mktemp` file pointed at by `GOOGLE_APPLICATION_CREDENTIALS`, cleaned up via `trap ... EXIT`. The `FIREBASE_TOKEN` fallback is documented as deprecated. Missing both secrets produces a GitHub `::error::` and a non-zero exit rather than a silent no-op (confirmed). The project id is resolved from `.firebaserc` (`deltagammavega-46877`), so `--project` is intentionally omitted — no inline guess (confirmed against the file).

Scope is clean: only `.github/workflows/update-cpurnsa-data.yml` changed, one commit, no stray working-tree edits, and `permissions: contents: write`, the `concurrency` group, and all existing steps are preserved unchanged (confirmed).

<details>
<summary>Issues (0)</summary>

No blocking or actionable issues.

</details>

<details>
<summary>Details</summary>

### Scope and preservation of existing job config

`git diff main...cpurnsa-auto-deploy --stat` shows one file, +50 lines, and the log shows a single commit `d6cbc2c`. `git status --porcelain` is empty, so nothing unrelated rode along. The diff is purely additive — it appends after the `Commit generated public data` step and touches no earlier line. The full file read confirms `permissions: contents: write` and the `concurrency: { group: cpurnsa-data-update, cancel-in-progress: true }` block are intact, and the six prior steps are byte-for-byte unchanged and in their original order. No `tools/*.py`, `firebase.json`, `.firebaserc`, `deploy_public_site.sh`, or site content was touched (confirmed).

### Deploy gating — fail-closed by sequential ordering

The two new steps (`Install firebase-tools`, `Deploy public build to Firebase Hosting`) have no `if:` key at all, so they inherit the default `success()` condition. GitHub Actions halts a job on the first failing step, so any failure in the handoff validation, rebuild, rebuilt-data validation, or `build_site.py`/`validate_public_build.py` assembly aborts before the deploy runs. There is no `if: always()` anywhere, which is exactly what point 3 requires — a validation failure cannot reach the publish.

### No-diff path still publishes

The commit step's early `exit 0` fires when `git diff --quiet` finds no changes to the three generated JSON files. That is a zero (success) exit, so the step counts as passed and the job proceeds to deploy. Since `build/public` is reassembled fresh every run by `build_site.py`, re-publishing on a no-diff run is intentional and keeps Hosting aligned with the current build. This matches point 4.

### Auth and secret handling

Service-account-first: when `FIREBASE_SERVICE_ACCOUNT` is non-empty, the JSON is written to a `mktemp` file with `printf '%s'` (no trailing newline injection), exported via `GOOGLE_APPLICATION_CREDENTIALS`, and removed on exit via `trap`. The credential value is passed through the `env:` block rather than interpolated into the `run:` script, so it is not exposed on the command line or in a rendered expression. `set -euo pipefail` plus `${VAR:-}` guards avoid unbound-variable aborts while still letting the explicit `else` branch emit `::error::` and `exit 1` when neither secret is set — fail-fast, not a silent skip. The `FIREBASE_TOKEN` fallback is present and documented as deprecated. Secret names are documented both in the YAML comment block and in `verification.md`. Matches points 5 and 8.

### Project id resolution

`--project` is omitted; firebase-tools resolves the default from `.firebaserc`, which the file read confirms is `deltagammavega-46877`. No literal project id is passed on any command line, and the comment explains the omission is deliberate. Matches point 6.

### Verification evidence

`verification.md` is present and specific: it records the parsed step ordering, confirms `deploy has if: False` (no `if:` key) and the absence of `if: always()`, enumerates the `env` keys actually present on the deploy step, documents the required/optional secrets in a table, and explicitly notes that a real `firebase deploy` was not run because no auth is available and the spec forbids it. Per instructions I did not re-run the PyYAML validation; I spot-checked the YAML indentation of the appended steps in the full-file read and it is consistent with the surrounding `steps:` entries. The evidence left no articulable doubt requiring further checks.

</details>

<details>
<summary>File map</summary>

- `.github/workflows/update-cpurnsa-data.yml` — appended a comment block plus `Install firebase-tools` and `Deploy public build to Firebase Hosting` steps after the existing commit step.

Full diff: `git -C /home/mark/deltagammavega/.worktrees/cpurnsa-auto-deploy diff main...cpurnsa-auto-deploy`

</details>

# Verification — cpurnsa-auto-deploy

## Change summary
Single-file edit to `.github/workflows/update-cpurnsa-data.yml`: added two steps
after the existing "Commit generated public data" step:
1. `Install firebase-tools` (`npm install -g firebase-tools` — Node is preinstalled on `ubuntu-latest`).
2. `Deploy public build to Firebase Hosting` (runs `firebase deploy --only hosting --non-interactive`).

No other files changed. `deploy_public_site.sh`, `tools/*.py`, `firebase.json`,
and `.firebaserc` are untouched.

## YAML validation
- **Tool:** PyYAML via `python3 -c "import yaml; yaml.safe_load(open(...))"`.
  (`python` is not installed; used `python3`.)
- **Result:** PASS — `YAML OK`, document loaded without error.

## Final step ordering (confirmed from parsed YAML)
1. Check out website
2. Set up Python
3. Validate committed sanitized model handoff
4. Rebuild public CPURNSA JSON
5. Validate rebuilt public data
6. Assemble and validate Firebase public build
7. Commit generated public data
8. Install firebase-tools
9. Deploy public build to Firebase Hosting

Ordering requirement satisfied: build/validate (steps 3–6) → commit (step 7) →
deploy (steps 8–9).

## Deploy gating (confirmed)
- The deploy step has **no `if:` key** (confirmed: `deploy has if: False`), and
  specifically **no `if: always()`**. All steps are plain sequential steps, so GitHub
  Actions stops on the first failure. A failure in any validation/build step (3–6)
  aborts the job before the deploy is reached — a validation failure never deploys.
- The commit step's no-diff early `exit 0` is a **successful** step exit (exit code 0),
  so it does not block the deploy step. The deploy therefore runs on both diff and
  no-diff runs, keeping live in sync even when there is no new data — as required,
  because `build/public` is reassembled fresh each run.

## Auth mechanism (confirmed)
- Deploy step reads secrets via `env` (confirmed: `deploy env keys:
  ['FIREBASE_SERVICE_ACCOUNT', 'FIREBASE_TOKEN']`).
- **Primary:** service account. `FIREBASE_SERVICE_ACCOUNT` JSON is written to a
  `mktemp` file, `GOOGLE_APPLICATION_CREDENTIALS` is exported to point at it, and
  `firebase deploy --only hosting --non-interactive` runs. The temp file is removed
  via a `trap ... EXIT`.
- **Fallback:** if `FIREBASE_SERVICE_ACCOUNT` is empty but `FIREBASE_TOKEN` is set,
  the step uses the deprecated `firebase deploy ... --token "$FIREBASE_TOKEN"`.
- If neither secret is set, the step fails fast with a GitHub Actions `::error::`.

## Project id
- `.firebaserc` is present at repo root with default project `deltagammavega-46877`.
  Because the default is pinned, `--project` is intentionally **omitted**;
  firebase-tools resolves the default from `.firebaserc`. No hardcoded project id,
  no `vars.FIREBASE_PROJECT_ID` fallback.

## Secrets the user must create in the GitHub repository
| Name | Required? | Expected contents |
|------|-----------|-------------------|
| `FIREBASE_SERVICE_ACCOUNT` | Required (primary) | Full JSON of a GCP service account key with Firebase Hosting deploy permission on project `deltagammavega-46877` (e.g. `roles/firebasehosting.admin`). |
| `FIREBASE_TOKEN` | Optional (deprecated fallback) | A `firebase login:ci` CI token. Only used if `FIREBASE_SERVICE_ACCOUNT` is unset. |

No GitHub Actions *variables* are required (project id comes from `.firebaserc`).

## Not run
A real `firebase deploy` was **not** executed — no network auth/secrets are available
in this environment, and the spec forbids it.

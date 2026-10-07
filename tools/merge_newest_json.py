#!/usr/bin/env python3
"""Git merge driver: resolve a conflict on a generated data/*.json file by
keeping whichever side carries the later ``generated_at_utc`` timestamp.

This replaces the old ``merge=binary`` behaviour for these files. Both drivers
refuse to interleave lines from the two versions (a line-based merge once
produced structurally-broken JSON in production, see .gitattributes). The
difference: ``binary`` always stopped and asked; this driver applies the
"last wins" rule the daily cron/manual sync already resolves by hand, and only
stops when it genuinely cannot decide.

Git invokes it as (see .gitattributes merge=newest):
    merge_newest_json.py %O %A %B %P
      %O  ancestor version (unused; path may be /dev/null for add/add)
      %A  current/ours version  -- ALSO the file the result must be written to
      %B  other/theirs version
      %P  the real pathname being merged (for diagnostics)

Exit 0  -> conflict resolved; the chosen content has been written to %A.
Exit 1  -> could not decide; leave a normal conflict for a human.

A whole side is always chosen; bytes from the two versions are never mixed.

Decision rule:
  * Both sides must parse as JSON objects carrying a top-level
    ``generated_at_utc`` string. If either lacks it or fails to parse, exit 1.
  * Parse both timestamps. The side with the later timestamp wins.
  * If timestamps are equal but content differs, exit 1 (ambiguous).
  * If content is identical, either side wins (exit 0).
"""
import json
import sys
from datetime import datetime, timezone

TS_KEY = "generated_at_utc"


def log(msg: str) -> None:
    # stderr only; stdout is not consumed by git for merge drivers.
    sys.stderr.write(f"[merge-newest] {msg}\n")


def load(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()
    return raw, json.loads(raw.decode("utf-8"))


def parse_ts(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating a trailing 'Z' and making the
    result timezone-aware (naive values are treated as UTC) so all sides are
    comparable."""
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main(argv) -> int:
    if len(argv) < 4:
        log("expected: %O %A %B [%P]; cannot run, leaving conflict")
        return 1
    _ancestor, ours, theirs = argv[1], argv[2], argv[3]
    path = argv[4] if len(argv) > 4 else ours

    try:
        ours_raw, ours_doc = load(ours)
        theirs_raw, theirs_doc = load(theirs)
    except Exception as exc:  # unreadable or not valid JSON -> human decides
        log(f"{path}: could not parse both sides as JSON ({exc}); leaving conflict")
        return 1

    if ours_raw == theirs_raw:
        log(f"{path}: sides identical; keeping ours")
        return 0

    if not (isinstance(ours_doc, dict) and isinstance(theirs_doc, dict)):
        log(f"{path}: a side is not a JSON object; leaving conflict")
        return 1

    if TS_KEY not in ours_doc or TS_KEY not in theirs_doc:
        log(f"{path}: missing '{TS_KEY}' on a side; leaving conflict")
        return 1

    try:
        ours_ts = parse_ts(str(ours_doc[TS_KEY]))
        theirs_ts = parse_ts(str(theirs_doc[TS_KEY]))
    except Exception as exc:
        log(f"{path}: unparseable '{TS_KEY}' ({exc}); leaving conflict")
        return 1

    if ours_ts == theirs_ts:
        log(f"{path}: equal '{TS_KEY}' ({ours_ts.isoformat()}) but differing "
            f"content; leaving conflict")
        return 1

    if theirs_ts > ours_ts:
        # Result must land in %A (ours); copy theirs' exact bytes over it.
        with open(ours, "wb") as fh:
            fh.write(theirs_raw)
        log(f"{path}: kept THEIRS ({theirs_ts.isoformat()} > {ours_ts.isoformat()})")
    else:
        log(f"{path}: kept OURS ({ours_ts.isoformat()} > {theirs_ts.isoformat()})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

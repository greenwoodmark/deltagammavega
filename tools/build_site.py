"""Assemble the public Firebase site."""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import uuid
from pathlib import Path

PUBLIC_FILES = (
    "index.html",
    "softs/logs.html",
    "cpurnsa.html",
    "pca.html",
    "chart.html",
    "cpi_bayesian_update_example.html",
    "404.html",
    "CNAME",
)
PUBLIC_DATA_FILES = (
    "softs_diagnostics.json",
    "cpurnsa_curve_history.json",
    "cpurnsa_daily_commentary.json",
    "cpurnsa_pca_diagnostics.json",
    "health.json",
)


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required site source is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _assemble_variant(root: Path, output: Path) -> None:
    shared = root / "site" / "shared"
    data = root / "data"

    for relative in PUBLIC_FILES:
        _copy(shared / relative, output / relative)
    for filename in PUBLIC_DATA_FILES:
        _copy(data / filename, output / "data" / filename)


def build_variant(root: Path, output: Path) -> None:
    """Build into a complete temporary tree, then atomically publish it."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    backup = output.with_name(f".{output.name}.{uuid.uuid4().hex}.old")
    try:
        _assemble_variant(root, temporary)
        if output.exists():
            os.replace(output, backup)
        os.replace(temporary, output)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists() and not output.exists():
            os.replace(backup, output)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # The internal variant now lives in the private repo (dgv_resources). This
    # builder produces the public site only. "all" is retained as a backward-
    # compatible alias that builds the public site.
    parser.add_argument("--target", choices=("public", "all"), default="public")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    build_dir = root / "build"
    if args.target in {"public", "all"}:
        build_variant(root, build_dir / "public")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

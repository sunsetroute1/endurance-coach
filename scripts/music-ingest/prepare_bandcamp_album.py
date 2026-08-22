#!/usr/bin/env python3
"""Prepare a Bandcamp download folder and optionally run beets import."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

INGEST_ROOT = Path(__file__).resolve().parents[2] / "services" / "music-ingest"
SRC = INGEST_ROOT / "src"
sys.path.insert(0, str(SRC))

from bandcamp_ingest import is_bandcamp_folder, prepare_bandcamp_folder  # noqa: E402
from pipeline_config import PipelineConfig  # noqa: E402


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Bandcamp album folder for beets import")
    parser.add_argument("folder", type=Path, help="Album folder with Bandcamp downloads")
    parser.add_argument("--url", help="Optional Bandcamp album URL")
    parser.add_argument("--import", dest="do_import", action="store_true", help="Run beets import after prep")
    args = parser.parse_args()

    folder = args.folder.resolve()
    if not folder.is_dir():
        print(f"Folder not found: {folder}", file=sys.stderr)
        return 1
    if not is_bandcamp_folder(folder):
        print(f"Not a Bandcamp download folder: {folder}", file=sys.stderr)
        return 1

    result = prepare_bandcamp_folder(folder, url=args.url)
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if not result.prepared:
        print("Bandcamp prep did not match any tracks.", file=sys.stderr)
        return 1

    print(f"Prepared {result.matched} track(s) using {result.url}")
    if not args.do_import:
        return 0

    env_file = INGEST_ROOT / "config" / "pipeline.env"
    load_env_file(env_file)
    config = PipelineConfig.from_env()
    beet = INGEST_ROOT / ".venv" / "Scripts" / "beet.exe"
    cmd = [
        str(beet),
        "-c",
        str(config.beets_config),
        "import",
        "-q",
        "--quiet-fallback=asis",
        "-I",
        "-m",
        str(folder),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.stdout.strip():
        print(proc.stdout.strip()[-3000:])
    if proc.stderr.strip():
        print(proc.stderr.strip()[-3000:], file=sys.stderr)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())

"""Repair junk titles (e.g. beets rewrite literal \\1) across the music library."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "music-ingest" / "src"))

from folder_tags import fix_library_on_disk, repair_junk_titles_library  # noqa: E402

DEFAULT_LIB = Path(r"E:\Music")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIB)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-folder-tags",
        action="store_true",
        help="skip the general folder/filename tag pass",
    )
    parser.add_argument(
        "--no-rename",
        action="store_true",
        help="retag only; do not rename junk filenames",
    )
    args = parser.parse_args()
    write = not args.dry_run

    if not args.skip_folder_tags:
        updated = fix_library_on_disk(args.library, write=write)
        print(f"Folder/filename tag pass updated {updated} file(s).")

    stats = repair_junk_titles_library(args.library, write=write, rename=not args.no_rename)
    print(
        "Junk title repair: "
        f"fixed={stats['fixed']}, removed={stats['removed']}, skipped={stats['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

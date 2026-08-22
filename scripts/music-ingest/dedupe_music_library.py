"""Remove duplicate tracks from the beets library and disk.

Phase 1: drop redundant beets rows that point at the same file path.
Phase 2: for matching artist/title/duration, keep the best on-disk copy and delete the rest.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MUSIC_ROOT = Path(r"E:\Music")
BEETS_DB = MUSIC_ROOT / "State" / "beets-library.blb"
BEET_EXE = Path(__file__).resolve().parents[2] / "services" / "music-ingest" / ".venv" / "Scripts" / "beet.exe"
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"

DEPRIORITIZE_PARTS = (
    "/incoming/",
    "/soulseek/",
    "/non-album/",
    "/quarantine/",
    "/state/",
)
AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".wma", ".aac", ".alac"}


@dataclass
class ItemRow:
    item_id: int
    path: str
    title: str
    artist: str
    album: str
    length: float

    @property
    def abs_path(self) -> Path:
        return MUSIC_ROOT / self.path.replace("/", "\\")


def log_line(log_file: Path, message: str) -> None:
    stamp = datetime.now(timezone.utc).astimezone().isoformat()
    line = f"{stamp} {message}"
    print(message)
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def normalize_text(value: str | None) -> str:
    text = (value or "").strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def path_score(path: str) -> int:
    normalized = path.replace("\\", "/").lower()
    score = 0
    for part in DEPRIORITIZE_PARTS:
        if part in normalized:
            score -= 120
    parts = [part for part in normalized.split("/") if part]
    if parts and parts[0] in {"incoming", "non-album", "quarantine", "state", "_"}:
        score -= 40
    if len(parts) >= 2:
        score += 40
    if len(parts) >= 3:
        score += 80
    if "/singles/" in normalized:
        score += 15
    suffix = Path(normalized).suffix
    if suffix == ".flac":
        score += 25
    elif suffix in {".m4a", ".alac"}:
        score += 10
    return score


def load_items() -> list[ItemRow]:
    conn = sqlite3.connect(BEETS_DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, path, title, artist, album, length FROM items")
    rows = [
        ItemRow(
            item_id=int(row["id"]),
            path=row["path"].decode() if isinstance(row["path"], bytes) else str(row["path"]),
            title=row["title"] or "",
            artist=row["artist"] or "",
            album=row["album"] or "",
            length=float(row["length"] or 0.0),
        )
        for row in cur.fetchall()
    ]
    conn.close()
    return rows


def file_hash(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.md5()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def choose_keep_item(items: list[ItemRow]) -> ItemRow:
    existing = [item for item in items if item.abs_path.is_file()]
    pool = existing or items
    return sorted(
        pool,
        key=lambda item: (
            -path_score(item.path),
            len(item.path),
            item.item_id,
        ),
    )[0]


def plan_db_only_dupes(items: list[ItemRow]) -> tuple[list[int], list[int]]:
    by_path: dict[str, list[ItemRow]] = defaultdict(list)
    for item in items:
        by_path[item.path].append(item)
    remove_ids: list[int] = []
    keep_ids: list[int] = []
    for path, group in by_path.items():
        if len(group) < 2:
            continue
        keep = choose_keep_item(group)
        keep_ids.append(keep.item_id)
        remove_ids.extend(item.item_id for item in group if item.item_id != keep.item_id)
    return sorted(set(remove_ids)), keep_ids


def plan_content_dupes(items: list[ItemRow], skip_ids: set[int]) -> tuple[list[int], list[int]]:
    by_key: dict[tuple[str, str, int], list[ItemRow]] = defaultdict(list)
    for item in items:
        if item.item_id in skip_ids:
            continue
        artist = normalize_text(item.artist)
        title = normalize_text(item.title)
        if not artist and not title:
            continue
        duration_key = int(round(item.length or 0.0))
        by_key[(artist, title, duration_key)].append(item)

    remove_ids: list[int] = []
    keep_ids: list[int] = []
    for group in by_key.values():
        if len(group) < 2:
            continue
        unique_paths = {item.path for item in group}
        if len(unique_paths) < 2:
            continue
        keep = choose_keep_item(group)
        keep_ids.append(keep.item_id)
        for item in group:
            if item.item_id == keep.item_id:
                continue
            remove_ids.append(item.item_id)
    return sorted(set(remove_ids)), keep_ids


def run_beet_remove(item_ids: list[int], delete_files: bool, log_file: Path, apply: bool) -> None:
    if not item_ids or not apply:
        return

    from beets import library

    lib = library.Library(str(BEETS_DB), str(MUSIC_ROOT))
    removed = 0
    missing = 0
    for item_id in item_ids:
        item = lib.get_item(item_id)
        if not item:
            missing += 1
            continue
        item.remove(delete=delete_files)
        removed += 1
        if removed % 100 == 0:
            log_line(log_file, f"Removed {removed}/{len(item_ids)} item(s)...")

    action = "deleted" if delete_files else "db-only"
    log_line(log_file, f"beet remove {action}: removed {removed}, missing {missing}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate beets music library")
    parser.add_argument("--apply", action="store_true", help="Perform removals (default is dry-run report)")
    parser.add_argument("--skip-content", action="store_true", help="Only remove redundant DB rows for the same path")
    args = parser.parse_args()

    if not BEET_EXE.is_file():
        print(f"beet not found: {BEET_EXE}", file=sys.stderr)
        return 1
    if not BEETS_DB.is_file():
        print(f"beets database not found: {BEETS_DB}", file=sys.stderr)
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "dedupe-music-library.log"
    log_file.write_text("", encoding="utf-8")

    items = load_items()
    log_line(log_file, f"Loaded {len(items)} beets item(s)")

    db_remove, db_keep = plan_db_only_dupes(items)
    log_line(log_file, f"Phase 1 same-path DB dupes: remove {len(db_remove)} row(s), keep {len(db_keep)} path(s)")

    content_remove: list[int] = []
    content_keep: list[int] = []
    if not args.skip_content:
        skip = set(db_remove)
        content_remove, content_keep = plan_content_dupes(items, skip)
        log_line(log_file, f"Phase 2 content dupes: remove {len(content_remove)} item(s), keep {len(content_keep)} canonical copy(ies)")

    if not args.apply:
        log_line(log_file, "Dry run only. Re-run with --apply to remove duplicates.")
        return 0

    run_beet_remove(db_remove, delete_files=False, log_file=log_file, apply=True)
    if content_remove:
        run_beet_remove(content_remove, delete_files=True, log_file=log_file, apply=True)

    remaining = load_items()
    log_line(log_file, f"Done. Items before={len(items)} after={len(remaining)} removed={len(items)-len(remaining)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

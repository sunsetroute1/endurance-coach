"""Repair A-Alikes tracks mis-tagged by Soulseek (00 Alikes junk artist, Singles dump)."""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "music-ingest" / "src"))

from folder_tags import (  # noqa: E402
    TRACK_PREFIX_JUNK,
    clean_loose_title,
    normalize_inferred_artist,
    read_easy_tags,
    resolve_artist_dir,
)

LIBDIR = Path(r"E:\Music")
ARTIST = "A-Alikes"
JUNK_ARTIST_DIRS = ("00 Alikes", "00 alikes (rbg)")

ALBUMS: dict[str, list[str]] = {
    "Kill the Middleman": [
        "Intro",
        "Pop Off",
        "Young buk to Og",
        "Love is Love",
        "Why",
        "Freedom",
        "Treeman",
        "Keep it funky",
        "What Niggaz do",
        "Trow ya guns",
        "Ill probably",
        "If i get on",
        "The Babies",
        "Some of us",
        "Snitch",
        "Eenie meanie",
        "Strategy",
        "Grey Skies",
    ],
    "Us Against Them EP": [
        "They Watchin",
        "Person Of Interest",
        "Whole Life",
        "Slingin' In The Rain",
        "Slingin In The Rain",
        "Currency",
        "Eat Right",
        "Song For You",
    ],
    "The Hustler The Hunted Part 2": [
        "Recap of part 1",
        "Get whut u deserve",
        "Ducking from the jakes",
        "The world is  a ghetto",
        "The world is a ghetto",
    ],
}


def normalize_title(value: str) -> str:
    text = clean_loose_title(value)
    text = TRACK_PREFIX_JUNK.sub("", text).strip()
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = re.sub(r"\s*feat\.?\s.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*ft\.?\s.*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().lower()


def album_for_title(title: str) -> str | None:
    needle = normalize_title(title)
    for album, tracks in ALBUMS.items():
        for track in tracks:
            norm = normalize_title(track)
            if norm == needle or norm in needle or needle in norm:
                return album
    return None


def title_from_path(path: Path, tags: dict[str, str | None]) -> str:
    title = tags.get("title")
    if title and title.strip():
        return clean_loose_title(title)
    stem = TRACK_PREFIX_JUNK.sub("", path.stem).strip()
    return clean_loose_title(stem)


def album_from_path(path: Path, title: str) -> str:
    if path.parent.name != ARTIST and path.parent.parent.name == ARTIST:
        folder_album = path.parent.name
        if folder_album != "Singles":
            return folder_album
    mapped = album_for_title(title)
    return mapped or "Singles"


def fix_tags(path: Path, *, write: bool = True) -> bool:
    audio, tags = read_easy_tags(path)
    if audio is None:
        return False

    title = title_from_path(path, tags)
    album = album_from_path(path, title)
    artist = ARTIST

    changed = False
    for key, value in (
        ("artist", artist),
        ("albumartist", artist),
        ("album", album),
        ("title", title),
    ):
        if tags.get(key) != value:
            audio[key] = value
            changed = True

    if write and changed:
        audio.save()
    return changed


def move_to_canonical(path: Path, *, write: bool = True) -> Path:
    audio, tags = read_easy_tags(path)
    if audio is None:
        return path

    title = title_from_path(path, tags)
    album = album_from_path(path, title)
    artist_dir = resolve_artist_dir(LIBDIR, ARTIST)
    dest_dir = LIBDIR / artist_dir / album
    dest = dest_dir / f"{title}{path.suffix.lower()}"

    if dest.resolve() == path.resolve():
        return path

    if not write:
        print(f"would move: {path} -> {dest}")
        return dest

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem} ({counter}){suffix}"
            counter += 1
    shutil.move(str(path), str(dest))
    return dest


def repair_tree(root: Path, *, write: bool = True) -> tuple[int, int]:
    moved = fixed = 0
    for path in sorted(root.rglob("*.mp3")):
        dest = move_to_canonical(path, write=write)
        if dest != path:
            moved += 1
            path = dest
        if fix_tags(path, write=write):
            fixed += 1
            if write:
                print(f"fixed: {path.relative_to(LIBDIR)}")
    return moved, fixed


def remove_junk_dirs(*, write: bool = True) -> None:
    for name in JUNK_ARTIST_DIRS:
        folder = LIBDIR / name
        if not folder.exists():
            continue
        if write:
            shutil.rmtree(folder)
            print(f"removed junk folder: {folder}")
        else:
            print(f"would remove junk folder: {folder}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Repair A-Alikes mis-tagged Soulseek imports")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    write = not args.dry_run

    canonical = LIBDIR / ARTIST
    if not canonical.is_dir():
        print(f"Missing canonical artist folder: {canonical}")
        return

    moved, fixed = repair_tree(canonical, write=write)

    for name in JUNK_ARTIST_DIRS:
        junk = LIBDIR / name
        if junk.is_dir():
            junk_moved, junk_fixed = repair_tree(junk, write=write)
            moved += junk_moved
            fixed += junk_fixed

    remove_junk_dirs(write=write)
    print(f"Repaired {fixed} tag(s), moved {moved} file(s).")


if __name__ == "__main__":
    main()

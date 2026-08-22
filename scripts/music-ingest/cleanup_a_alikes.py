"""Dedupe and reorganize A-Alikes library after bad beets singleton imports."""

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
    read_easy_tags,
    resolve_artist_dir,
)

LIBDIR = Path(r"E:\Music")
ARTIST = "A-Alikes"
ARTIST_ROOT = LIBDIR / ARTIST
NON_ALBUM = LIBDIR / "Non-Album"

HUSTLER_3_TITLES = {
    "hh3 intro",
    "since 9 11",
    "do your time",
    "currency",
    "a black verse",
    "if i should die",
    "hh3 pirate radio call in",
    "treeman part 2 featuring raye 6",
    "difference a day makes",
    "we everywhere",
    "heartbeat of the streets",
    "a.r.t. (all real things)",
    "winner never quits",
    "rbg salute ft. dj victorious",
    "the sheep and the shepherd",
    "u next",
    "sirens in the distance ft. mos def",
    "we gon miss u mike",
    "last election",
    "death of the industry",
    "explode",
    "how do we go",
    "dj victorious and zarakyah pirate radio interlude",
}

KILL_THE_MIDDLEMAN = {
    "intro", "pop off", "young buk to og", "love is love", "why", "freedom",
    "treeman", "keep it funky", "what niggaz do", "trow ya guns", "ill probably",
    "if i get on", "the babies", "some of us", "snitch", "eenie meanie", "strategy",
    "grey skies",
}

US_AGAINST_THEM = {
    "they watchin", "person of interest", "whole life", "slingin in the rain",
    "slingin' in the rain", "eat right", "song for you",
}


def normalize_title(value: str) -> str:
    text = clean_loose_title(value)
    text = TRACK_PREFIX_JUNK.sub("", text).strip()
    text = re.sub(r"\s*\(\d+\)\s*$", "", text)
    text = re.sub(r"\.\d+$", "", text)
    text = re.sub(r"\s*\([^)]*\)\s*", " ", text)
    text = re.sub(r"\s*feat\.?\s.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*ft\.?\s.*$", "", text, flags=re.IGNORECASE)
    text = text.replace("_", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def safe_filename(title: str) -> str:
    # Windows forbids \ / : * ? " < > |
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    return cleaned or "track"


def title_from_path(path: Path, tags: dict[str, str | None]) -> str:
    title = tags.get("title")
    if title and title.strip():
        return clean_loose_title(title)
    stem = TRACK_PREFIX_JUNK.sub("", path.stem).strip()
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"\.\d+$", "", stem)
    return clean_loose_title(stem)


def album_for_title(title: str, current_album: str) -> str:
    key = normalize_title(title)
    if key in HUSTLER_3_TITLES:
        return "The Hustler and The Hunted 3"
    if key in KILL_THE_MIDDLEMAN:
        return "Kill the Middleman"
    if key in US_AGAINST_THEM:
        return "Us Against Them EP"
    if current_album not in ("Singles", ARTIST) and current_album:
        return current_album
    return "Singles"


def keeper_score(path: Path, norm: str) -> tuple[int, int, int, int]:
    stem = path.stem.lower()
    album = path.parent.name
    dup = 10 if re.search(r"\(\d+\)$", stem) or re.search(r"\.\d+$", stem) else 0
    if album == "Singles":
        album_rank = 5
    elif "hustler" in album.lower() and norm in HUSTLER_3_TITLES:
        album_rank = 0
    elif album in ("Kill the Middleman", "Us Against Them EP"):
        album_rank = 1
    else:
        album_rank = 3
    prefix = 1 if re.match(r"^\d+\.?\s", stem) else 0
    return (dup, album_rank, prefix, len(stem))


def collect_files() -> list[Path]:
    files: list[Path] = []
    if ARTIST_ROOT.is_dir():
        files.extend(ARTIST_ROOT.rglob("*.mp3"))
    if NON_ALBUM.is_dir():
        files.extend(NON_ALBUM.glob("*Alikes*.mp3"))
    return sorted(set(files))


def dedupe(*, write: bool = True) -> int:
    groups: dict[str, list[Path]] = {}
    for path in collect_files():
        _, tags = read_easy_tags(path)
        title = title_from_path(path, tags or {})
        key = normalize_title(title)
        if key:
            groups.setdefault(key, []).append(path)

    removed = 0
    for key, paths in sorted(groups.items()):
        if len(paths) < 2:
            continue
        keeper = min(paths, key=lambda p: keeper_score(p, key))
        for path in paths:
            if path == keeper:
                continue
            if write:
                path.unlink(missing_ok=True)
                print(f"removed duplicate: {path.relative_to(LIBDIR)}")
            else:
                print(f"would remove duplicate: {path.relative_to(LIBDIR)}")
            removed += 1
    return removed


def reorganize(*, write: bool = True) -> tuple[int, int]:
    moved = fixed = 0
    artist_dir = resolve_artist_dir(LIBDIR, ARTIST)
    for path in list(collect_files()):
        if not path.exists():
            continue
        audio, tags = read_easy_tags(path)
        if audio is None:
            continue
        title = title_from_path(path, tags)
        current_album = path.parent.name if path.parent.parent == ARTIST_ROOT else "Singles"
        album = album_for_title(title, current_album)
        dest_dir = LIBDIR / artist_dir / album
        dest = dest_dir / f"{safe_filename(title)}{path.suffix.lower()}"

        for key, value in (
            ("artist", ARTIST),
            ("albumartist", ARTIST),
            ("album", album),
            ("title", title),
        ):
            if tags.get(key) != value:
                audio[key] = value

        if dest.resolve() != path.resolve():
            if not write:
                print(f"would move: {path} -> {dest}")
                moved += 1
                continue
            dest_dir.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                path.unlink(missing_ok=True)
                print(f"removed extra copy: {path.relative_to(LIBDIR)}")
                continue
            shutil.move(str(path), str(dest))
            path = dest
            moved += 1
            print(f"moved: {path.relative_to(LIBDIR)}")

        if write:
            audio.save()
            fixed += 1
    return moved, fixed


def prune_empty_dirs() -> None:
    for root in (ARTIST_ROOT, NON_ALBUM):
        if not root.is_dir():
            continue
        for folder in sorted(root.rglob("*"), reverse=True):
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                print(f"removed empty dir: {folder.relative_to(LIBDIR)}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Dedupe and clean A-Alikes library")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    write = not args.dry_run

    removed = dedupe(write=write)
    moved, fixed = reorganize(write=write)
    if write:
        prune_empty_dirs()
    print(f"Removed {removed} duplicate(s), moved {moved}, retagged {fixed}.")


if __name__ == "__main__":
    main()

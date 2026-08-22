"""Move remaining incoming A-Alikes album tracks into library."""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "services" / "music-ingest" / "src"))

from folder_tags import TRACK_PREFIX_JUNK, clean_loose_title, read_easy_tags  # noqa: E402

LIBDIR = Path(r"E:\Music")
INCOMING = LIBDIR / "Incoming" / "Soulseek" / "2009-The Hustler And The Hunted Part.3"
ARTIST = "A-Alikes"
ALBUM = "The Hustler and The Hunted 3"


def title_from_path(path: Path, tags: dict[str, str | None]) -> str:
    title = tags.get("title")
    if title and title.strip():
        return clean_loose_title(title)
    return clean_loose_title(TRACK_PREFIX_JUNK.sub("", path.stem).strip())


def main() -> None:
    dest_dir = LIBDIR / ARTIST / ALBUM
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved = 0
    for path in sorted(INCOMING.glob("*.mp3")):
        audio, tags = read_easy_tags(path)
        title = title_from_path(path, tags or {})
        dest = dest_dir / f"{title}{path.suffix.lower()}"
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            n = 2
            while dest.exists():
                dest = dest_dir / f"{stem} ({n}){suffix}"
                n += 1
        if audio is not None:
            for key, value in (("artist", ARTIST), ("albumartist", ARTIST), ("album", ALBUM), ("title", title)):
                audio[key] = value
            audio.save()
        shutil.move(str(path), str(dest))
        print(f"moved: {dest.relative_to(LIBDIR)}")
        moved += 1
    if INCOMING.exists() and not any(INCOMING.iterdir()):
        INCOMING.rmdir()
    print(f"Done: {moved} track(s) -> {ARTIST}/{ALBUM}")


if __name__ == "__main__":
    main()

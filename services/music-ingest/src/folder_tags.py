"""Fill album tags from parent folder when artist is known; shared by beets plugin and disk backfill."""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePath

DEFAULT_JUNK = [
    r"^\s*$",
    r"^\[cover\]$",
    r"^\[unknown\]$",
    r"^unknown album$",
    r"^unknown artist$",
    r"^unknown$",
    # Soulseek placeholder folders/tags like [218], [97], [0000]
    r"^\[\d+\]$",
    # Beets rewrite plugin uses literal replacements (not regex backrefs). A rule like
    # `title ^\d+\.?\s+(.+)$: \1` writes the two-character title "\1" into tags.
    r"^\\1$",
    # Beets %aunique{} disambiguation suffixes when merging duplicate track numbers.
    r"^_\d+$",
    r"^_\d+\.\d+$",
    r"^\d+\.\d+$",
    r"^\d{1,2}$",
]

BRACKET_ALBUM = re.compile(r"^\[\d+\]$", re.IGNORECASE)
TRACK_PREFIX_JUNK = re.compile(r"^\d{1,2}\.?\s+", re.IGNORECASE)
TRACK_PREFIX_ARTIST_FOLDER = re.compile(r"^\d{1,2}\.?\s+.+\S", re.IGNORECASE)
TRACK_NUM_SHORT_JUNK_FOLDER = re.compile(r"^\d{1,2}\s+[A-Za-z0-9]$", re.IGNORECASE)
# Beets %aunique{} suffixes embedded in filenames after duplicate track collisions.
BEETS_AUNIQUE_FILENAME = re.compile(
    r" _1(?:\.\d+)?\.(?:mp3|m4a|flac|ogg|opus|wma|aac|alac)$| _1\.(?:mp3|m4a|flac|ogg|opus|wma|aac|alac)$",
    re.IGNORECASE,
)
STUB_MAX_BYTES = 500_000
SIZE_MATCH_TOLERANCE = 0.03

RESERVED_DIRS = {
    "incoming",
    "state",
    "quarantine",
    "non-album",
    "compilations",
    "soundtracks",
    "soulseek",
    "incomplete",
    "_",
}

AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".wma", ".aac", ".alac"}

# Soulseek / manual rip filename patterns (stem only, no extension).
FILENAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "bandcamp-downloader",
        re.compile(
            r"^BandCampDownloader\.app\s*-\s*(?P<title>.+?)(?:\s*-\s*(?P<artist>.+))?$",
            re.IGNORECASE,
        ),
    ),
    (
        "artist-album-track-title",
        re.compile(
            r"^(?P<artist>.+?) - (?P<album>.+?) - (?P<track>\d+)\.?\s*(?P<title>.+)$",
            re.IGNORECASE,
        ),
    ),
    (
        "track-artist-title",
        re.compile(
            r"^(?P<track>\d+)\.?\s*-\s*(?P<artist>.+?)\s*-\s*(?P<title>.+?)(?:\s*-\s*(?P<tag>.*))?$",
            re.IGNORECASE,
        ),
    ),
    (
        "track_artist_title_underscore",
        re.compile(
            r"^(?P<track>\d+)_(?P<artist>.+?)_-_(?P<title>.+?)(?:_\[.*)?$",
            re.IGNORECASE,
        ),
    ),
    (
        "artist-title",
        re.compile(r"^(?P<artist>.+?)\s*-\s*(?P<title>.+)$", re.IGNORECASE),
    ),
    (
        "track-title",
        re.compile(r"^(?P<track>\d+)\.?\s*(?P<title>.+)$", re.IGNORECASE),
    ),
    (
        "track_sep_title",
        re.compile(r"^(?P<track>\d+)[\s._-]+(?P<title>.+)$", re.IGNORECASE),
    ),
    (
        "track_artist_title_loose",
        re.compile(
            r"^(?P<track>\d+)\.?\s*(?P<artist>.+?)\s*-\s*(?:(?P<track2>\d+)\.?\s*)?(?P<title>.+)$",
            re.IGNORECASE,
        ),
    ),
]


def compile_junk(patterns: list[str] | None = None) -> list[re.Pattern[str]]:
    source = patterns or DEFAULT_JUNK
    return [re.compile(pat, re.IGNORECASE) for pat in source]


def is_junk(value: str | None, patterns: list[re.Pattern[str]]) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    if TRACK_PREFIX_JUNK.match(text):
        return True
    return any(pat.match(text) for pat in patterns)


def folder_names_for_path(path: Path | str, libdir: Path | str) -> tuple[str | None, str | None]:
    """Return (artist_dir, album_dir) for Artist/Album/track or Artist/track under libdir."""
    try:
        rel = os.path.relpath(str(path), str(libdir))
    except ValueError:
        return None, None

    parts = PurePath(rel).parts
    if len(parts) < 2:
        return None, None

    if parts[0].lower() in RESERVED_DIRS:
        return None, None

    if len(parts) == 2:
        artist = parts[0]
        if artist.lower() in RESERVED_DIRS:
            return None, None
        return artist, "Singles"

    artist = parts[-3]
    album = parts[-2]

    if album.lower() in RESERVED_DIRS:
        return None, None
    if artist.lower() in RESERVED_DIRS:
        return None, None
    # Never treat Soulseek [218] folders as album names.
    if BRACKET_ALBUM.match(album):
        album = None

    return artist, album


def in_bracket_album_folder(path: Path, libdir: Path) -> tuple[str | None, bool]:
    try:
        rel = path.relative_to(libdir)
    except ValueError:
        return None, False
    if len(rel.parts) < 3:
        return None, False
    if not BRACKET_ALBUM.match(rel.parts[-2]):
        return None, False
    artist_dir = rel.parts[-3]
    if artist_dir.lower() in RESERVED_DIRS:
        return None, True
    return artist_dir, True


def known_artist(
    tag_artist: str | None,
    tag_albumartist: str | None,
    folder_artist: str | None,
    junk_artist_patterns: list[re.Pattern[str]],
) -> str | None:
    for value in (tag_albumartist, tag_artist, folder_artist):
        if value and not is_junk(value, junk_artist_patterns):
            return value
    return None


def album_from_folder(
    tag_album: str | None,
    folder_album: str | None,
    tag_artist: str | None,
    tag_albumartist: str | None,
    folder_artist: str | None,
    junk_album_patterns: list[re.Pattern[str]],
    junk_artist_patterns: list[re.Pattern[str]],
) -> str | None:
    """When artist is already known, use parent folder as album if tag is junk."""
    if not folder_album or is_junk(folder_album, junk_album_patterns):
        return None
    if not is_junk(tag_album, junk_album_patterns):
        return None
    if not known_artist(tag_artist, tag_albumartist, folder_artist, junk_artist_patterns):
        return None
    return folder_album


def parse_filename(stem: str) -> dict[str, str]:
    """Extract artist/album/title/track from common filename patterns."""
    for _, pattern in FILENAME_PATTERNS:
        match = pattern.match(stem.strip())
        if match:
            return {k: v.strip() for k, v in match.groupdict().items() if v and k != "tag"}
    return {}


def read_easy_tags(path: Path) -> tuple[object | None, dict[str, str | None]]:
    import mutagen
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3, ID3NoHeaderError

    audio = None
    try:
        if path.suffix.lower() == ".mp3":
            try:
                audio = EasyID3(path)
            except ID3NoHeaderError:
                easy = EasyID3()
                easy.save(path)
                audio = EasyID3(path)
            except mutagen.id3.error:
                # Corrupt ID3 header (e.g. synchsafe errors) — strip and recreate.
                try:
                    ID3(path).delete()
                except Exception:
                    pass
                easy = EasyID3()
                easy.save(path)
                audio = EasyID3(path)
        else:
            audio = mutagen.File(path, easy=True)
    except Exception:
        return None, {}
    if audio is None:
        return None, {}

    tags: dict[str, str | None] = {}
    for key in ("artist", "albumartist", "album", "title", "tracknumber", "discnumber", "date", "genre"):
        raw = audio.get(key)
        if raw:
            tags[key] = str(raw[0] if isinstance(raw, list) else raw)
    return audio, tags


def pick_field(
    tag_value: str | None,
    file_value: str | None,
    folder_value: str | None,
    junk_patterns: list[re.Pattern[str]],
) -> str | None:
    for value in (tag_value, file_value, folder_value):
        if value and not is_junk(value, junk_patterns):
            return value.strip()
    return None


def in_unknown_album_folder(path: Path, libdir: Path) -> tuple[str | None, bool]:
    try:
        rel = path.relative_to(libdir)
    except ValueError:
        return None, False
    if len(rel.parts) < 3:
        return None, False
    if rel.parts[-2].lower() != "unknown album":
        return None, False
    artist_dir = rel.parts[-3]
    if artist_dir.lower() in RESERVED_DIRS or artist_dir.lower() == "unknown artist":
        return None, True
    return artist_dir, True


def merge_unknown_album_metadata(
    path: Path,
    libdir: Path,
    junk_album_patterns: list[re.Pattern[str]],
    junk_artist_patterns: list[re.Pattern[str]],
) -> dict[str, str]:
    """Combine embedded tags + filename + parent artist folder for Unknown Album paths."""
    folder_artist, is_unknown = in_unknown_album_folder(path, libdir)
    if not is_unknown:
        return {}

    _, tags = read_easy_tags(path)
    parsed = parse_filename(path.stem)

    track = pick_field(tags.get("tracknumber"), parsed.get("track"), None, junk_album_patterns)
    if track and "/" in track:
        track = track.split("/", 1)[0]

    artist = pick_field(
        tags.get("artist"),
        parsed.get("artist"),
        folder_artist,
        junk_artist_patterns,
    )
    albumartist = pick_field(tags.get("albumartist"), parsed.get("artist"), folder_artist, junk_artist_patterns)
    album = pick_field(tags.get("album"), parsed.get("album"), None, junk_album_patterns)
    title = pick_field(tags.get("title"), parsed.get("title"), None, junk_album_patterns)

    updates: dict[str, str] = {}
    if artist:
        updates["artist"] = artist
    if albumartist:
        updates["albumartist"] = albumartist
    if album:
        updates["album"] = album
    if title:
        updates["title"] = title
    if track and track.isdigit():
        updates["tracknumber"] = track
    return updates


def fix_unknown_album_file(
    path: Path,
    libdir: Path,
    junk_album_patterns,
    junk_artist_patterns,
    write: bool,
) -> bool:
    return repair_unknown_album_entry(path, libdir, junk_album_patterns, junk_artist_patterns, write)[0]


def repair_unknown_album_entry(
    path: Path,
    libdir: Path,
    junk_album_patterns,
    junk_artist_patterns,
    write: bool,
) -> tuple[bool, bool]:
    """Repair tags in Unknown Album folders and move when artist+album are known."""
    folder_artist, is_unknown = in_unknown_album_folder(path, libdir)
    if not is_unknown:
        return False, False

    audio, tags = read_easy_tags(path)
    if audio is None:
        return False, False

    tag_changed = False
    album = tags.get("album")
    if album and is_junk(album, junk_album_patterns):
        if "album" in audio:
            del audio["album"]
            tags["album"] = None
            tag_changed = True

    merged = merge_unknown_album_metadata(path, libdir, junk_album_patterns, junk_artist_patterns)
    for key, value in merged.items():
        if tags.get(key) != value:
            audio[key] = value
            tag_changed = True
            tags[key] = value

    if tag_changed and write:
        audio.save()

    artist = pick_field(
        tags.get("artist"),
        merged.get("artist"),
        folder_artist,
        junk_artist_patterns,
    )
    album = pick_field(tags.get("album"), merged.get("album"), None, junk_album_patterns)
    if not artist or not album:
        return tag_changed, False

    moved = move_to_tagged_album(path, libdir, artist, album, write)
    return tag_changed, moved


def reconcile_unknown_albums(libdir: Path, write: bool = True) -> dict[str, int]:
    """Full Unknown Album pass: folder tags, metadata/filenames, and moves."""
    junk_album = compile_junk()
    junk_artist = compile_junk()
    stats = {
        "folder_tags_fixed": 0,
        "unknown_folder_tags_fixed": 0,
        "unknown_folder_moved": 0,
        "folders_cleaned": 0,
    }

    for path in iter_audio_files(libdir):
        try:
            folder_artist, folder_album = folder_names_for_path(path, libdir)
            if folder_album and in_unknown_album_folder(path, libdir)[1]:
                continue
            if folder_album and fix_file_tags(path, libdir, junk_album, junk_artist, write):
                stats["folder_tags_fixed"] += 1
        except Exception:
            continue

    for folder in libdir.rglob("Unknown Album"):
        if not folder.is_dir():
            continue
        rel = folder.relative_to(libdir)
        if rel.parts and rel.parts[0].lower() in RESERVED_DIRS:
            continue
        for path in list(folder.iterdir()):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                tag_changed, moved = repair_unknown_album_entry(
                    path, libdir, junk_album, junk_artist, write
                )
                if tag_changed:
                    stats["unknown_folder_tags_fixed"] += 1
                if moved:
                    stats["unknown_folder_moved"] += 1
            except Exception:
                continue
        if write and folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
            stats["folders_cleaned"] += 1

    return stats


def iter_audio_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0].lower() in RESERVED_DIRS:
            continue
        yield path


def fix_file_tags(path: Path, libdir: Path, junk_album_patterns, junk_artist_patterns, write: bool) -> bool:
    if fix_unknown_album_file(path, libdir, junk_album_patterns, junk_artist_patterns, write):
        return True

    folder_artist, folder_album = folder_names_for_path(path, libdir)
    if not folder_artist or folder_artist.lower() in RESERVED_DIRS or is_junk_artist_folder(folder_artist):
        return False

    audio, tags = read_easy_tags(path)
    if audio is None:
        return False

    changed = False
    artist = known_artist(tags.get("artist"), tags.get("albumartist"), folder_artist, junk_artist_patterns)
    if artist:
        artist = normalize_inferred_artist(artist)
        for key in ("artist", "albumartist"):
            current = tags.get(key)
            if not current or is_junk(current, junk_artist_patterns):
                if current != artist:
                    audio[key] = artist
                    changed = True

    parsed = parse_filename(path.stem)
    title = pick_field(tags.get("title"), parsed.get("title"), None, junk_album_patterns)
    if title:
        title = clean_loose_title(title)
    if not title or is_junk(tags.get("title"), junk_album_patterns):
        recovered = title_from_path_stem(path, junk_album_patterns)
        if recovered:
            title = recovered
    if title and (not tags.get("title") or is_junk(tags.get("title"), junk_album_patterns)):
        if tags.get("title") != title:
            audio["title"] = title
            changed = True

    new_album = album_from_folder(
        tags.get("album"),
        folder_album,
        tags.get("artist"),
        tags.get("albumartist"),
        folder_artist,
        junk_album_patterns,
        junk_artist_patterns,
    )
    if new_album and tags.get("album") != new_album:
        audio["album"] = new_album
        changed = True
    elif (
        folder_album
        and not is_junk(folder_album, junk_album_patterns)
        and (not tags.get("album") or is_junk(tags.get("album"), junk_album_patterns))
        and tags.get("album") != folder_album
    ):
        audio["album"] = folder_album
        changed = True

    if changed and write:
        audio.save()
    return changed


def fix_unknown_album_folders(libdir: Path, write: bool = True) -> int:
    stats = reconcile_unknown_albums(libdir, write=write)
    return stats["unknown_folder_tags_fixed"] + stats["unknown_folder_moved"]


def move_to_tagged_album(path: Path, libdir: Path, artist: str, album: str, write: bool) -> bool:
    import shutil

    dest_dir = libdir / artist / album
    dest = dest_dir / path.name
    if dest.resolve() == path.resolve():
        return False
    if not write:
        return True
    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem} ({counter}){suffix}"
            counter += 1
    shutil.move(str(path), str(dest))
    return True


def repair_bracket_album_entry(
    path: Path,
    libdir: Path,
    junk_album_patterns,
    junk_artist_patterns,
    write: bool,
) -> tuple[bool, bool]:
    """Fix [NNN] album tags and move files into Artist/Album/ when possible."""
    folder_artist, in_bracket = in_bracket_album_folder(path, libdir)
    audio, tags = read_easy_tags(path)
    if audio is None:
        return False, False

    tag_changed = False
    album = tags.get("album")
    if album and (is_junk(album, junk_album_patterns) or BRACKET_ALBUM.match(album.strip())):
        parsed = parse_filename(path.stem)
        recovered = pick_field(None, parsed.get("album"), None, junk_album_patterns)
        if recovered:
            audio["album"] = recovered
            tags["album"] = recovered
        elif "album" in audio:
            del audio["album"]
            tags["album"] = None
        tag_changed = True

    merged = merge_unknown_album_metadata(path, libdir, junk_album_patterns, junk_artist_patterns)
    for key, value in merged.items():
        if tags.get(key) != value:
            audio[key] = value
            tag_changed = True
            tags[key] = value

    if tag_changed and write:
        audio.save()

    artist = pick_field(
        tags.get("artist"),
        merged.get("artist"),
        folder_artist,
        junk_artist_patterns,
    )
    album = pick_field(tags.get("album"), merged.get("album"), None, junk_album_patterns)
    if not artist or not album:
        return tag_changed, False

    moved = move_to_tagged_album(path, libdir, artist, album, write)
    return tag_changed, moved


def fix_bracket_album_folders(libdir: Path, write: bool = True) -> tuple[int, int]:
    junk_album = compile_junk()
    junk_artist = compile_junk()
    tags_fixed = 0
    moved = 0
    for folder in libdir.rglob("*"):
        if not folder.is_dir() or not BRACKET_ALBUM.match(folder.name):
            continue
        rel = folder.relative_to(libdir)
        if rel.parts and rel.parts[0].lower() in RESERVED_DIRS:
            continue
        for path in list(folder.iterdir()):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            try:
                tag_changed, was_moved = repair_bracket_album_entry(
                    path, libdir, junk_album, junk_artist, write
                )
                if tag_changed:
                    tags_fixed += 1
                if was_moved:
                    moved += 1
            except Exception:
                continue
        if write and folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
    return tags_fixed, moved


def resolve_artist_dir(libdir: Path, artist: str) -> str:
    """Prefer an existing artist folder over creating a differently-cased duplicate."""
    target = libdir / artist
    if target.is_dir():
        return artist
    artist_key = artist.casefold()
    for entry in libdir.iterdir():
        if entry.is_dir() and entry.name.casefold() == artist_key:
            return entry.name
    return artist


FLOGGING_MOLLY_FOLDER = re.compile(r"^\d{1,2}_Flogging_Molly_$", re.IGNORECASE)
SINGLE_CHAR_FOLDER = re.compile(r"^[A-Za-z]$")
NUMERIC_JUNK_FOLDER = re.compile(r"^\d{1,2}$")
QUARANTINE_EXTENSIONS = {".m4p"}
M4P_EXTENSIONS = {".m4p"}


def normalize_inferred_artist(name: str) -> str:
    cleaned = name.strip()
    if re.match(r"^\d+\.?\s*alikes?", cleaned, re.IGNORECASE):
        return "A-Alikes"
    if re.match(r"^alikes", cleaned, re.IGNORECASE):
        return "A-Alikes"
    if TRACK_PREFIX_JUNK.match(cleaned):
        stripped = TRACK_PREFIX_JUNK.sub("", cleaned).strip()
        if re.match(r"^alikes?", stripped, re.IGNORECASE):
            return "A-Alikes"
        if stripped:
            return stripped
    if cleaned.lower() in {"ky"}:
        return "KY"
    return cleaned


def clean_loose_title(title: str) -> str:
    text = title.strip()
    text = re.sub(r"^\d+\.?\s+", "", text)
    text = text.replace("_", " ")
    text = re.sub(r"\s*\[mp3n\]\s*$", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def title_from_path_stem(path: Path, junk_patterns: list[re.Pattern[str]] | None = None) -> str | None:
    """Recover a display title from the filename when tags are missing or junk."""
    junk = junk_patterns or compile_junk()
    parsed = parse_filename(path.stem)
    for candidate in (parsed.get("title"),):
        if candidate:
            cleaned = clean_loose_title(candidate)
            if cleaned and not is_junk(cleaned, junk):
                return cleaned
    loose = re.match(r"^(?P<track>\d+)\.?\s*(?P<rest>.+)$", path.stem)
    if loose:
        cleaned = clean_loose_title(loose.group("rest"))
        if cleaned and not is_junk(cleaned, junk):
            return cleaned
    # Files like "Audobon Ballroom (feat X).mp3" with no numeric prefix.
    if not re.match(r"^\d", path.stem):
        cleaned = clean_loose_title(path.stem)
        if cleaned and not is_junk(cleaned, junk):
            return cleaned
    return None


def safe_track_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", title).strip()
    return cleaned or "track"


def parse_leading_track(stem: str) -> str | None:
    match = re.match(r"^(\d{1,2})", stem)
    return match.group(1) if match else None


def parse_tracknumber_tag(value: str | None) -> int | None:
    if not value:
        return None
    head = str(value).split("/")[0].strip()
    if not head.isdigit():
        return None
    num = int(head)
    return num if num > 0 else None


def parse_discnumber_tag(value: str | None) -> int | None:
    if not value:
        return None
    head = str(value).split("/")[0].strip()
    if not head.isdigit():
        return None
    num = int(head)
    return num if num > 0 else None


def file_sort_key(path: Path) -> tuple[int, str]:
    match = re.match(r"^(\d+)", path.stem)
    track = int(match.group(1)) if match else 9999
    return track, path.stem.lower()


def is_proper_multi_disc(files: list[Path]) -> bool:
    discs: list[int] = []
    for path in files:
        _, tags = read_easy_tags(path)
        disc = parse_discnumber_tag(tags.get("discnumber") if tags else None)
        if disc:
            discs.append(disc)
    if len(set(discs)) < 2:
        return False
    by_disc: dict[int, list[int]] = {}
    for path in files:
        _, tags = read_easy_tags(path)
        disc = parse_discnumber_tag(tags.get("discnumber") if tags else None) or 1
        track = parse_tracknumber_tag(tags.get("tracknumber") if tags else None)
        if track:
            by_disc.setdefault(disc, []).append(track)
    return all(len(tracks) == len(set(tracks)) for tracks in by_disc.values())


def needs_track_order_repair(files: list[Path]) -> bool:
    if len(files) < 2:
        return False
    if is_proper_multi_disc(files):
        return False
    sorted_files = sorted(files, key=file_sort_key)
    tag_nums = []
    for path in sorted_files:
        _, tags = read_easy_tags(path)
        tag_nums.append(parse_tracknumber_tag(tags.get("tracknumber") if tags else None))
    if any(n is None for n in tag_nums):
        return True
    if len(set(tag_nums)) != len(tag_nums):
        return True
    expected = list(range(1, len(sorted_files) + 1))
    return tag_nums != expected


def repair_album_track_order(
    folder: Path,
    libdir: Path,
    junk_patterns: list[re.Pattern[str]],
    *,
    write: bool,
    rename_files: bool,
) -> int:
    files = [
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    ]
    if not needs_track_order_repair(files):
        return 0

    updated = 0
    sorted_files = sorted(files, key=file_sort_key)
    total = len(sorted_files)
    for index, path in enumerate(sorted_files, start=1):
        audio, tags = read_easy_tags(path)
        if audio is None:
            continue
        title = tags.get("title") if tags else None
        if title is not None:
            title = str(title).strip()
        if not title or is_junk(title, junk_patterns):
            title = title_from_path_stem(path, junk_patterns)
        if not title:
            continue

        track_str = str(index)
        total_str = str(total)
        changed = False
        current_track = parse_tracknumber_tag(tags.get("tracknumber"))
        if current_track != index:
            audio["tracknumber"] = track_str
            changed = True
        # Drop bogus disc 0/0 tags from bad Soulseek rips; single-folder albums are one disc.
        disc = parse_discnumber_tag(tags.get("discnumber") if tags else None)
        if disc not in (None, 1):
            audio["discnumber"] = "1"
            changed = True
        elif tags.get("discnumber") and str(tags.get("discnumber")) != "1":
            try:
                del audio["discnumber"]
                changed = True
            except Exception:
                audio["discnumber"] = "1"
                changed = True

        dest = path
        if rename_files:
            dest = folder / f"{index:02d} {safe_track_filename(title)}{path.suffix.lower()}"
            if dest.resolve() != path.resolve():
                counter = 1
                base = dest.stem
                while dest.exists():
                    dest = dest.with_name(f"{base} ({counter}){dest.suffix}")
                    counter += 1

        if write:
            if changed:
                audio.save()
            if dest.resolve() != path.resolve():
                import shutil

                shutil.move(str(path), str(dest))
            updated += 1
            print(f"track {track_str}/{total_str}: {dest.relative_to(libdir)}")
        else:
            updated += 1
            print(f"would set track {track_str}/{total_str}: {path.relative_to(libdir)} -> {dest.name}")
    return updated


def repair_track_order_library(
    libdir: Path,
    *,
    write: bool = True,
    rename_files: bool = True,
) -> dict[str, int]:
    junk_patterns = compile_junk()
    by_folder: dict[Path, list[Path]] = {}
    for path in iter_audio_files(libdir):
        by_folder.setdefault(path.parent, []).append(path)

    stats = {"albums": 0, "tracks": 0}
    for folder in sorted(by_folder):
        count = repair_album_track_order(
            folder, libdir, junk_patterns, write=write, rename_files=rename_files
        )
        if count:
            stats["albums"] += 1
            stats["tracks"] += count
    return stats


def has_junk_title(path: Path, tag_title: str | None, junk_patterns: list[re.Pattern[str]]) -> bool:
    if not tag_title or is_junk(tag_title, junk_patterns):
        return True
    if BEETS_AUNIQUE_FILENAME.search(path.name):
        return True
    return False


def build_album_size_title_index(folder: Path, junk_patterns: list[re.Pattern[str]]) -> dict[int, str]:
    index: dict[int, str] = {}
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if BEETS_AUNIQUE_FILENAME.search(path.name):
            continue
        _, tags = read_easy_tags(path)
        title = tags.get("title") if tags else None
        if not title or is_junk(title, junk_patterns):
            continue
        index[path.stat().st_size] = title.strip()
    return index


def title_from_album_size(size: int, size_index: dict[int, str]) -> str | None:
    if size in size_index:
        return size_index[size]
    best_title = None
    best_delta = float("inf")
    for ref_size, title in size_index.items():
        delta = abs(size - ref_size) / max(ref_size, 1)
        if delta <= SIZE_MATCH_TOLERANCE and delta < best_delta:
            best_delta = delta
            best_title = title
    return best_title


def resolve_recovered_title(path: Path, junk_patterns: list[re.Pattern[str]]) -> str | None:
    _, tags = read_easy_tags(path)
    tag_title = tags.get("title") if tags else None
    if tag_title and not is_junk(tag_title, junk_patterns):
        return tag_title.strip()

    from_name = title_from_path_stem(path, junk_patterns)
    if from_name:
        return from_name

    if path.parent.is_dir() and path.parent.parent != path.parent:
        size_index = build_album_size_title_index(path.parent, junk_patterns)
        return title_from_album_size(path.stat().st_size, size_index)
    return None


def repair_junk_title_file(
    path: Path,
    libdir: Path,
    junk_patterns: list[re.Pattern[str]],
    *,
    write: bool,
    rename: bool,
) -> tuple[bool, str | None]:
    if path.suffix.lower() not in AUDIO_EXTENSIONS:
        return False, None

    try:
        size = path.stat().st_size
    except OSError:
        return False, None

    if size <= STUB_MAX_BYTES and path.suffix.lower() == ".mp3" and BEETS_AUNIQUE_FILENAME.search(path.name):
        if write:
            path.unlink(missing_ok=True)
        return True, f"removed stub {path.relative_to(libdir)}"

    _, tags = read_easy_tags(path)
    tag_title = tags.get("title") if tags else None
    if not has_junk_title(path, tag_title, junk_patterns):
        return False, None

    title = resolve_recovered_title(path, junk_patterns)
    if not title:
        return False, None

    audio, tags = read_easy_tags(path)
    if audio is None:
        return False, None

    track = parse_leading_track(path.stem)
    folder_artist, folder_album = folder_names_for_path(path, libdir)
    changed = False
    if tags.get("title") != title:
        audio["title"] = title
        changed = True
    if track:
        track_str = str(int(track))
        if tags.get("tracknumber") != track_str:
            audio["tracknumber"] = track_str
            changed = True
    if folder_artist and is_junk(tags.get("artist"), junk_patterns):
        audio["artist"] = folder_artist
        changed = True
    if folder_artist and is_junk(tags.get("albumartist"), junk_patterns):
        audio["albumartist"] = folder_artist
        changed = True
    if folder_album and is_junk(tags.get("album"), junk_patterns):
        audio["album"] = folder_album
        changed = True

    dest = path
    if rename and (BEETS_AUNIQUE_FILENAME.search(path.name) or is_junk(tag_title, junk_patterns)):
        dest_stem = f"{track} {title}" if track else title
        dest = path.parent / f"{safe_track_filename(dest_stem)}{path.suffix.lower()}"
        if dest.resolve() != path.resolve():
            counter = 1
            base = dest.stem
            while dest.exists():
                dest = dest.with_name(f"{base} ({counter}){dest.suffix}")
                counter += 1

    if write:
        if changed:
            audio.save()
        if dest.resolve() != path.resolve():
            import shutil

            shutil.move(str(path), str(dest))
        rel = dest.relative_to(libdir)
        return True, f"fixed {rel}"
    rel = dest.relative_to(libdir)
    return True, f"would fix {rel}"


def repair_junk_titles_library(
    libdir: Path,
    *,
    write: bool = True,
    rename: bool = True,
) -> dict[str, int]:
    junk_patterns = compile_junk()
    stats = {"fixed": 0, "skipped": 0, "removed": 0}
    for path in iter_audio_files(libdir):
        try:
            ok, msg = repair_junk_title_file(
                path, libdir, junk_patterns, write=write, rename=rename
            )
        except Exception:
            stats["skipped"] += 1
            continue
        if not ok:
            continue
        if msg:
            print(msg)
            if msg.startswith("removed stub"):
                stats["removed"] += 1
            else:
                stats["fixed"] += 1
        else:
            stats["skipped"] += 1
    return stats


def infer_artist_from_junk_folder(folder_name: str) -> str | None:
    if FLOGGING_MOLLY_FOLDER.match(folder_name):
        return "Flogging Molly"
    if folder_name == "Fun_":
        return "fun."
    if folder_name == "(HED) P.E_":
        return "(HED) P.E."
    if folder_name.endswith("_") and len(folder_name) > 2:
        base = folder_name.rstrip("_").replace("_", " ")
        return base
    return None


def is_junk_artist_folder(name: str) -> bool:
    lower = name.lower()
    if lower in RESERVED_DIRS:
        return False
    if name == "_":
        return True
    if FLOGGING_MOLLY_FOLDER.match(name):
        return True
    if SINGLE_CHAR_FOLDER.match(name):
        return True
    if NUMERIC_JUNK_FOLDER.match(name):
        return True
    if TRACK_PREFIX_ARTIST_FOLDER.match(name):
        return True
    if TRACK_NUM_SHORT_JUNK_FOLDER.match(name):
        return True
    if name.lower() in {"unknown artist", "unknown artist."}:
        return True
    if name in {"Fun_", "(HED) P.E_"}:
        return True
    if name.startswith("_") and name.endswith("_"):
        return True
    if name.endswith("_") and len(name) > 3:
        return True
    return False


def infer_track_metadata(path: Path, junk_folder_name: str) -> tuple[str | None, str | None, str | None]:
    junk_album = compile_junk()
    junk_artist = compile_junk()
    _, tags = read_easy_tags(path)
    parsed = parse_filename(path.stem)

    artist = pick_field(tags.get("artist"), parsed.get("artist"), None, junk_artist)
    title = pick_field(tags.get("title"), parsed.get("title"), None, junk_album)
    track = pick_field(tags.get("tracknumber"), parsed.get("track"), None, junk_album)

    if artist:
        artist = normalize_inferred_artist(artist)
    elif parsed.get("artist"):
        artist = normalize_inferred_artist(parsed["artist"])

    if not artist:
        artist = infer_artist_from_junk_folder(junk_folder_name)

    if title:
        title = clean_loose_title(title)
    elif parsed.get("title"):
        title = clean_loose_title(parsed["title"])
    elif not artist or artist == infer_artist_from_junk_folder(junk_folder_name):
        loose = re.match(r"^(?P<track>\d+)\.?\s*(?P<rest>.+)$", path.stem)
        if loose:
            track = track or loose.group("track")
            title = clean_loose_title(loose.group("rest"))

    if artist and title and title.lower().startswith(artist.lower()):
        title = title[len(artist) :].lstrip(" -")

    return artist, title, track


def move_singles_file(
    path: Path,
    libdir: Path,
    artist: str,
    title: str,
    write: bool,
) -> bool:
    import shutil

    artist_dir = resolve_artist_dir(libdir, artist)
    dest_dir = libdir / artist_dir / "Singles"
    dest_name = f"{title}{path.suffix}"
    dest = dest_dir / dest_name
    if dest.resolve() == path.resolve():
        return False
    if not write:
        return True

    audio, tags = read_easy_tags(path)
    if audio is not None:
        for key, value in (
            ("artist", artist),
            ("albumartist", artist),
            ("album", "Singles"),
            ("title", title),
        ):
            if tags.get(key) != value:
                audio[key] = value
        audio.save()

    dest_dir.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        stem, suffix = dest.stem, dest.suffix
        counter = 2
        while dest.exists():
            dest = dest_dir / f"{stem} ({counter}){suffix}"
            counter += 1
    shutil.move(str(path), str(dest))
    return True


def consolidate_junk_artist_folders(libdir: Path, write: bool = True) -> dict[str, int]:
    import shutil
    from datetime import datetime

    stats = {"folders": 0, "moved": 0, "removed": 0, "skipped": 0, "quarantined": 0}
    quarantine = libdir / "Quarantine" / "unparseable"
    stamp = datetime.now().strftime("%Y%m%d")

    for entry in sorted(libdir.iterdir()):
        if not entry.is_dir() or not is_junk_artist_folder(entry.name):
            continue
        singles = entry / "Singles"
        stats["folders"] += 1

        seen: set[Path] = set()
        for path in list(entry.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            if path in seen:
                continue
            seen.add(path)
            artist, title, _track = infer_track_metadata(path, entry.name)
            if not artist or not title:
                stats["skipped"] += 1
                if write:
                    bucket = quarantine / stamp
                    bucket.mkdir(parents=True, exist_ok=True)
                    dest = bucket / path.name
                    if dest.exists():
                        dest = bucket / f"{entry.name}_{path.name}"
                    shutil.move(str(path), str(dest))
                    stats["quarantined"] += 1
                continue
            if move_singles_file(path, libdir, artist, title, write):
                stats["moved"] += 1

        if write:
            for sub in sorted(entry.rglob("*"), reverse=True):
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()
                    stats["removed"] += 1
            audio_left = [
                p for p in entry.rglob("*")
                if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
            ]
            if not audio_left and entry.exists():
                shutil.rmtree(entry)
                stats["removed"] += 1

    return stats


def quarantine_unsupported_files(libdir: Path, write: bool = True) -> dict[str, int]:
    import shutil
    from datetime import datetime

    quarantine = libdir / "Quarantine"
    drm_dir = quarantine / "drm-m4p"
    unparseable_dir = quarantine / "unparseable"
    stats = {"m4p": 0, "unparseable": 0}

    def move_to(dest_root: Path, path: Path) -> None:
        dest_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d")
        bucket = dest_root / stamp
        bucket.mkdir(parents=True, exist_ok=True)
        dest = bucket / path.name
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            counter = 2
            while dest.exists():
                dest = bucket / f"{stem} ({counter}){suffix}"
                counter += 1
        shutil.move(str(path), str(dest))

    non_album = libdir / "Non-Album"
    if non_album.is_dir():
        junk_album = compile_junk()
        junk_artist = compile_junk()
        for path in list(non_album.iterdir()):
            if not path.is_file():
                continue
            if path.suffix.lower() in M4P_EXTENSIONS:
                if write:
                    move_to(drm_dir, path)
                stats["m4p"] += 1
                continue

            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                if write:
                    move_to(unparseable_dir, path)
                stats["unparseable"] += 1
                continue

            parsed = parse_filename(path.stem)
            _, tags = read_easy_tags(path)
            artist = pick_field(tags.get("artist"), parsed.get("artist"), None, junk_artist)
            title = pick_field(tags.get("title"), parsed.get("title"), None, junk_album)
            if artist and title:
                continue
            if write:
                move_to(unparseable_dir, path)
            stats["unparseable"] += 1

        if write and non_album.exists() and not any(non_album.iterdir()):
            non_album.rmdir()

    return stats


SKIP_UNKNOWN_ALBUM_ROOTS = {"incoming", "state", "quarantine"}


def remove_art_only_unknown_album_folders(libdir: Path, write: bool = True) -> int:
    removed = 0
    for folder in libdir.rglob("Unknown Album"):
        if not folder.is_dir():
            continue
        rel = folder.relative_to(libdir)
        if rel.parts and rel.parts[0].lower() in SKIP_UNKNOWN_ALBUM_ROOTS:
            continue
        has_audio = any(
            p.suffix.lower() in AUDIO_EXTENSIONS for p in folder.iterdir() if p.is_file()
        )
        if has_audio:
            continue
        if write:
            import shutil

            shutil.rmtree(folder)
        removed += 1
    return removed


def organize_non_album_singles(libdir: Path, write: bool = True) -> dict[str, int]:
    """Move beets singleton dump files into Artist/Singles/ with tags from filenames."""
    non_album = libdir / "Non-Album"
    if not non_album.is_dir():
        return {"processed": 0, "tagged": 0, "moved": 0, "skipped": 0}

    junk_album = compile_junk()
    junk_artist = compile_junk()
    stats = {"processed": 0, "tagged": 0, "moved": 0, "skipped": 0}

    for path in sorted(non_album.iterdir()):
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        stats["processed"] += 1

        audio, tags = read_easy_tags(path)
        if audio is None:
            stats["skipped"] += 1
            continue

        parsed = parse_filename(path.stem)
        artist = pick_field(tags.get("artist"), parsed.get("artist"), None, junk_artist)
        title = pick_field(tags.get("title"), parsed.get("title"), None, junk_album)
        if not artist or not title:
            stats["skipped"] += 1
            continue

        artist_dir = resolve_artist_dir(libdir, artist)
        album = "Singles"
        tag_changed = False

        for key, value in (
            ("artist", artist),
            ("albumartist", artist),
            ("album", album),
            ("title", title),
        ):
            if tags.get(key) != value:
                audio[key] = value
                tag_changed = True

        if tag_changed and write:
            audio.save()
            stats["tagged"] += 1

        dest_name = f"{title}{path.suffix}"
        dest_dir = libdir / artist_dir / album
        dest = dest_dir / dest_name
        if dest.resolve() == path.resolve():
            continue
        if not write:
            stats["moved"] += 1
            continue

        dest_dir.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            counter = 2
            while dest.exists():
                dest = dest_dir / f"{stem} ({counter}){suffix}"
                counter += 1
        import shutil

        shutil.move(str(path), str(dest))
        stats["moved"] += 1

    if write and non_album.exists() and not any(non_album.iterdir()):
        non_album.rmdir()

    return stats


def quarantine_library_root_files(libdir: Path, write: bool = True) -> int:
    """Move stray audio files sitting directly under the library root into Quarantine."""
    import shutil
    from datetime import datetime

    quarantine = libdir / "Quarantine" / "root-loose"
    stamp = datetime.now().strftime("%Y%m%d")
    bucket = quarantine / stamp
    moved = 0
    for path in libdir.iterdir():
        if not path.is_file() or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        if write:
            bucket.mkdir(parents=True, exist_ok=True)
            dest = bucket / path.name
            if dest.exists():
                stem, suffix = dest.stem, dest.suffix
                counter = 2
                while dest.exists():
                    dest = bucket / f"{stem} ({counter}){suffix}"
                    counter += 1
            shutil.move(str(path), str(dest))
        moved += 1
    return moved


def fix_library_on_disk(libdir: Path, write: bool = True) -> int:
    junk_album = compile_junk()
    junk_artist = compile_junk()
    updated = 0
    for path in iter_audio_files(libdir):
        try:
            if fix_file_tags(path, libdir, junk_album, junk_artist, write):
                updated += 1
        except Exception:
            continue
    return updated


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Set album tag from parent folder when artist is known.")
    parser.add_argument("library", nargs="?", default=r"E:\Music")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--unknown-album-only",
        action="store_true",
        help="only repair files inside Unknown Album folders (tags + filenames)",
    )
    parser.add_argument(
        "--bracket-albums-only",
        action="store_true",
        help="fix Soulseek [218] junk album tags and move to real Artist/Album folders",
    )
    parser.add_argument(
        "--reconcile-unknown-albums",
        action="store_true",
        help="fix Unknown Album tags from folders/metadata and move resolved tracks",
    )
    parser.add_argument(
        "--organize-non-album",
        action="store_true",
        help="move Non-Album singletons into Artist/Singles/ using filename tags",
    )
    parser.add_argument(
        "--consolidate-junk-artists",
        action="store_true",
        help="merge mis-parsed junk artist folders into real Artist/Singles paths",
    )
    parser.add_argument(
        "--quarantine-unsupported",
        action="store_true",
        help="move DRM .m4p and unparseable Non-Album files to Quarantine/",
    )
    parser.add_argument(
        "--quarantine-root-loose",
        action="store_true",
        help="move audio files sitting directly under the library root into Quarantine/",
    )
    parser.add_argument(
        "--remove-art-unknown-albums",
        action="store_true",
        help="delete Unknown Album folders that only contain Windows art cache",
    )
    parser.add_argument(
        "--repair-junk-titles",
        action="store_true",
        help="recover junk titles (e.g. beets rewrite \\\\1) from filenames and album peers",
    )
    parser.add_argument(
        "--repair-track-order",
        action="store_true",
        help="renumber album tracks 1..N in filename order (fixes duplicate/missing track tags)",
    )
    args = parser.parse_args()
    libdir = Path(args.library)
    write = not args.dry_run
    if args.bracket_albums_only:
        tags_fixed, moved = fix_bracket_album_folders(libdir, write=write)
        print(f"Fixed {tags_fixed} tag(s), moved {moved} file(s).")
    elif args.reconcile_unknown_albums:
        stats = reconcile_unknown_albums(libdir, write=write)
        print(
            "Reconciled Unknown Album: "
            f"folder_tags={stats['folder_tags_fixed']}, "
            f"unknown_tags={stats['unknown_folder_tags_fixed']}, "
            f"moved={stats['unknown_folder_moved']}, "
            f"folders_cleaned={stats['folders_cleaned']}"
        )
    elif args.organize_non_album:
        stats = organize_non_album_singles(libdir, write=write)
        print(
            "Organized Non-Album: "
            f"processed={stats['processed']}, "
            f"tagged={stats['tagged']}, "
            f"moved={stats['moved']}, "
            f"skipped={stats['skipped']}"
        )
    elif args.consolidate_junk_artists:
        stats = consolidate_junk_artist_folders(libdir, write=write)
        print(
            "Consolidated junk artists: "
            f"folders={stats['folders']}, "
            f"moved={stats['moved']}, "
            f"removed={stats['removed']}, "
            f"skipped={stats['skipped']}, "
            f"quarantined={stats['quarantined']}"
        )
    elif args.quarantine_unsupported:
        stats = quarantine_unsupported_files(libdir, write=write)
        print(f"Quarantined m4p={stats['m4p']}, unparseable={stats['unparseable']}")
    elif args.remove_art_unknown_albums:
        removed = remove_art_only_unknown_album_folders(libdir, write=write)
        print(f"Removed {removed} art-only Unknown Album folder(s).")
    elif args.quarantine_root_loose:
        moved = quarantine_library_root_files(libdir, write=write)
        print(f"Quarantined {moved} root-level audio file(s).")
    elif args.repair_junk_titles:
        stats = repair_junk_titles_library(libdir, write=write, rename=True)
        print(
            "Repaired junk titles: "
            f"fixed={stats['fixed']}, removed={stats['removed']}, skipped={stats['skipped']}"
        )
    elif args.repair_track_order:
        stats = repair_track_order_library(libdir, write=write, rename_files=True)
        print(f"Repaired track order: albums={stats['albums']}, tracks={stats['tracks']}")
    elif args.unknown_album_only:
        count = fix_unknown_album_folders(libdir, write=write)
        print(f"Updated {count} file(s).")
    else:
        count = fix_library_on_disk(libdir, write=write)
        print(f"Updated {count} file(s).")

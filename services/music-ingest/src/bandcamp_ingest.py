"""Prepare Bandcamp downloads (BandCampDownloader, etc.) before beets import."""

from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from folder_tags import AUDIO_EXTENSIONS, read_easy_tags

logger = logging.getLogger("music_ingest.bandcamp")

BANDCAMP_DOWNLOADER_PREFIX = re.compile(r"^BandCampDownloader\.app\s*-\s*", re.IGNORECASE)
BANDCAMP_SUFFIX = re.compile(r"\s*-\s*(?P<artist>.+?)\s*$", re.IGNORECASE)
URL_FILE_NAMES = ("bandcamp.url", "url.txt", ".bandcamp-url")
COVER_NAMES = ("cover.jpg", "folder.jpg", "front.jpg", "cover.png", "folder.png")


@dataclass
class BandcampAlbum:
    url: str
    artist: str
    album: str
    year: str | None
    tracks: list[str]
    cover_url: str | None


@dataclass
class PrepareResult:
    prepared: bool
    url: str | None = None
    matched: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def normalize_title(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("_", " ").replace("&amp;", "&").strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def slugify(text: str) -> str:
    text = html.unescape(text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def list_audio_files(folder: Path) -> list[Path]:
    return sorted(
        path
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
    )


def is_bandcamp_folder(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    if any((folder / name).is_file() for name in URL_FILE_NAMES):
        return True
    for path in list_audio_files(folder):
        if BANDCAMP_DOWNLOADER_PREFIX.match(path.stem):
            return True
    return False


def read_url_file(folder: Path) -> str | None:
    for name in URL_FILE_NAMES:
        path = folder / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("http") and "bandcamp.com" in line:
                return line.split()[0]
    return None


def album_hints(folder: Path) -> tuple[str | None, str | None]:
    artist = None
    album = None
    for path in list_audio_files(folder):
        _, tags = read_easy_tags(path)
        artist = artist or tags.get("albumartist") or tags.get("artist")
        album = album or tags.get("album")
        if artist and album:
            break
    if not album:
        album = folder.name
    return artist, album


def fetch_album(url: str) -> BandcampAlbum:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "endurance-coach-music-ingest/1.0"},
    )
    page = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
    match = re.search(r'data-tralbum="([^"]+)"', page)
    if not match:
        raise RuntimeError(f"Bandcamp metadata not found at {url}")
    data = json.loads(match.group(1).replace("&quot;", '"'))
    current = data.get("current", {})
    tracks = [html.unescape(t["title"]) for t in data.get("trackinfo", [])]
    art_id = data.get("art_id")
    cover_url = f"https://f4.bcbits.com/img/a{art_id}_10.jpg" if art_id else None
    release_date = current.get("release_date") or current.get("publish_date") or data.get("album_release_date")
    year = None
    if release_date is not None:
        match = re.search(r"(19|20)\d{2}", str(release_date))
        if match:
            year = match.group(0)
    return BandcampAlbum(
        url=url,
        artist=html.unescape(data.get("artist") or current.get("artist") or ""),
        album=html.unescape(current.get("title") or ""),
        year=year,
        tracks=tracks,
        cover_url=cover_url,
    )


def verify_album(candidate: BandcampAlbum, folder: Path) -> bool:
    files = list_audio_files(folder)
    if not candidate.tracks or not files:
        return False
    if len(candidate.tracks) != len(files):
        return False
    local_keys = {parse_filename_key(path.stem)[0] for path in files}
    remote_keys = {normalize_title(title) for title in candidate.tracks}
    overlap = len(local_keys & remote_keys)
    return overlap >= max(1, int(len(files) * 0.6))


def candidate_urls(artist: str | None, album: str | None) -> list[str]:
    if not artist or not album:
        return []
    album_slug = slugify(album)
    if not album_slug:
        return []

    artist_slug_candidates: list[str] = []
    for token in re.split(r"\s+", artist.strip()):
        slug = slugify(token)
        if slug and slug not in artist_slug_candidates:
            artist_slug_candidates.append(slug)
    full_slug = slugify(artist)
    if full_slug and full_slug not in artist_slug_candidates:
        artist_slug_candidates.append(full_slug)

    urls: list[str] = []
    for artist_slug in artist_slug_candidates:
        urls.append(f"https://{artist_slug}.bandcamp.com/album/{album_slug}")
    return urls


def resolve_bandcamp_url(folder: Path, explicit_url: str | None = None) -> str | None:
    if explicit_url:
        return explicit_url
    from_file = read_url_file(folder)
    if from_file:
        return from_file

    artist, album = album_hints(folder)
    for url in candidate_urls(artist, album):
        try:
            candidate = fetch_album(url)
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError, ValueError):
            continue
        if verify_album(candidate, folder):
            logger.info("Resolved Bandcamp URL for %s: %s", folder.name, url)
            return url
    return None


def parse_filename_key(stem: str) -> tuple[str, str | None]:
    artist = None
    stem = BANDCAMP_DOWNLOADER_PREFIX.sub("", stem).strip()
    suffix = BANDCAMP_SUFFIX.search(stem)
    if suffix:
        artist = suffix.group("artist").strip()
        stem = stem[: suffix.start()].strip()
    return normalize_title(stem), artist


def match_track(title_key: str, tracks: list[str]) -> tuple[int, str] | None:
    for index, title in enumerate(tracks, start=1):
        if title_key == normalize_title(title):
            return index, title

    aliases = {
        "keep bouncin": "keep bouncin'",
        "4th goal": "4th & goal",
    }
    alias = aliases.get(title_key)
    if alias:
        for index, title in enumerate(tracks, start=1):
            if normalize_title(title) == normalize_title(alias):
                return index, title
    return None


def write_tags(
    path: Path,
    *,
    track_num: int,
    title: str,
    artist: str,
    album: str,
    year: str | None,
) -> None:
    from mutagen.easyid3 import EasyID3

    try:
        audio = EasyID3(path)
    except Exception:
        audio = EasyID3()
    audio["title"] = title
    audio["artist"] = artist
    audio["albumartist"] = artist
    audio["album"] = album
    if year:
        audio["date"] = year
    audio["tracknumber"] = str(track_num)
    audio.save(path)


def download_cover(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "endurance-coach-music-ingest/1.0"})
    dest.write_bytes(urllib.request.urlopen(request, timeout=60).read())


def _fallback_filename_cleanup(folder: Path, result: PrepareResult) -> PrepareResult:
    """Strip BandCampDownloader junk from filenames using embedded tags when URL lookup fails."""
    changed = 0
    for path in list_audio_files(folder):
        if not BANDCAMP_DOWNLOADER_PREFIX.match(path.stem):
            continue
        _, tags = read_easy_tags(path)
        title = tags.get("title") or parse_filename_key(path.stem)[0]
        track = tags.get("tracknumber", "0").split("/")[0]
        try:
            track_num = int(track)
        except ValueError:
            track_num = 0
        clean_name = (
            f"{track_num:02d} {title}{path.suffix}" if track_num else f"{title}{path.suffix}"
        )
        dest = path.with_name(clean_name)
        if dest != path:
            if dest.exists():
                dest.unlink()
            path.rename(dest)
            changed += 1
    if changed:
        result.prepared = True
        result.matched = changed
        logger.info("Bandcamp fallback cleanup renamed %s file(s) in %s", changed, folder)
    return result


def prepare_bandcamp_folder(folder: Path, url: str | None = None) -> PrepareResult:
    """Clean Bandcamp download filenames/tags and fetch cover art."""
    result = PrepareResult(prepared=False)
    if not is_bandcamp_folder(folder):
        return result

    resolved = resolve_bandcamp_url(folder, explicit_url=url)
    if not resolved:
        result.warnings.append(
            "Could not resolve Bandcamp album URL; add bandcamp.url with the album link."
        )
        return _fallback_filename_cleanup(folder, result)

    try:
        meta = fetch_album(resolved)
    except (urllib.error.URLError, RuntimeError, json.JSONDecodeError, ValueError) as exc:
        result.warnings.append(f"Failed to fetch Bandcamp metadata: {exc}")
        return _fallback_filename_cleanup(folder, result)

    result.url = resolved
    artist = meta.artist or album_hints(folder)[0] or folder.parent.name
    album = meta.album or folder.name

    if meta.cover_url:
        cover_path = folder / "cover.jpg"
        if not cover_path.exists() or cover_path.stat().st_size < 5000:
            try:
                download_cover(meta.cover_url, cover_path)
            except urllib.error.URLError as exc:
                result.warnings.append(f"Cover download failed: {exc}")

    for path in list_audio_files(folder):
        title_key, _file_artist = parse_filename_key(path.stem)
        matched = match_track(title_key, meta.tracks)
        if not matched:
            result.skipped += 1
            result.warnings.append(f"No track match for {path.name}")
            continue

        track_num, title = matched
        write_tags(
            path,
            track_num=track_num,
            title=title,
            artist=artist,
            album=album,
            year=meta.year,
        )
        clean_name = f"{track_num:02d} {title}{path.suffix}"
        dest = path.with_name(clean_name)
        if dest != path:
            if dest.exists():
                dest.unlink()
            path.rename(dest)
        result.matched += 1

    result.prepared = result.matched > 0
    if result.prepared:
        logger.info(
            "Prepared Bandcamp folder %s (%s matched, %s skipped)",
            folder,
            result.matched,
            result.skipped,
        )
    return result

#!/usr/bin/env python3
"""Make Bazarr fetch English SRTs instead of treating PGS/VobSub as enough.

Jellyfin Web cannot render image subtitles without burning them into the
video. This updates live Bazarr config, assigns the English profile, and
triggers missing-subtitle searches. API keys are read from disk and never
printed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

BAZARR_CFG = Path(r"C:\ProgramData\docker\media-stack\config\bazarr\config\config.yaml")
BAZARR = "http://127.0.0.1:6767"
JELLYFIN = "http://127.0.0.1:8096"
VIDEO_ROOT = Path(r"E:\Video")
DOCKER_VIDEO_PREFIX = "/media/video"
FILL_MISSING_BATCH = 80
ENGLISH = {"en", "eng", "english"}
TEXT_CODECS = {"subrip", "srt", "webvtt", "mov_text"}
SIDECAR_SUFFIXES = (".srt", ".vtt")
# Longest Sonarr/Radarr prefixes must be listed first. Bazarr applies the first
# matching substring and stops, so a short "E:\Video" mapping rewrites
# "/app/sonarr/bin/E:\Video\..." into a path that does not exist.
WANTED_PATH_MAPS = [
    [r"/app/sonarr/bin/E:\Video", "/media/video"],
    ["/app/sonarr/bin/E:/Video", "/media/video"],
    ["/app/sonarr/bin//media/video", "/media/video"],
    ["/app/sonarr/bin/media/video", "/media/video"],
    [r"/app/radarr/bin/E:\Video", "/media/video"],
    ["/app/radarr/bin/E:/Video", "/media/video"],
    ["/app/radarr/bin//media/video", "/media/video"],
    ["/app/radarr/bin/media/video", "/media/video"],
    [r"E:\Video", "/media/video"],
    ["E:/Video", "/media/video"],
]
SKIP_WINDOWS_PATHS = {
    r"E:\Video\TV SHOWS\Alien Earth\www.UIndex.org    -    Alien Earth S01E04 Observation 2160p DSNP WEB-DL DDP5 1 DV HDR HEVC-NTb\Alien Earth S01E04 Observation 2160p DSNP WEB-DL DDP5 1 DV HDR HEVC-NTb.mkv",
}


def load_config() -> dict[str, Any]:
    return yaml.safe_load(BAZARR_CFG.read_text(encoding="utf-8"))


def apply_policy(data: dict[str, Any]) -> bool:
    general = data.setdefault("general", {})
    before = (
        general.get("ignore_pgs_subs"),
        general.get("ignore_vobsub_subs"),
        general.get("use_embedded_subs"),
        general.get("path_mappings"),
        general.get("path_mappings_movie"),
    )
    general["ignore_pgs_subs"] = True
    general["ignore_vobsub_subs"] = True
    # Sidecar SRT only. Embedded PGS/VobSub/text do not count as "have subtitles".
    general["use_embedded_subs"] = False
    general["single_language"] = True
    general["use_radarr"] = True
    general["use_jellyfin"] = True
    for key in ("path_mappings", "path_mappings_movie"):
        general[key] = ordered_path_mappings(general.get(key))
    after = (
        general.get("ignore_pgs_subs"),
        general.get("ignore_vobsub_subs"),
        general.get("use_embedded_subs"),
        general.get("path_mappings"),
        general.get("path_mappings_movie"),
    )
    return before != after


def ordered_path_mappings(current: object) -> list[list[str]]:
    """Drop prefix rewrites that share one destination.

    Bazarr keeps the first match and stops. Several sources mapped to
    /media/video make the reverse lookup miss the real Sonarr/Radarr path,
    so subtitle search never sees an IMDb id. Libraries already mounted at
    /media/video do not need these rewrites.
    """
    blocked = {src for src, _dst in WANTED_PATH_MAPS}
    return [
        [str(src), str(dst)]
        for src, dst in (current or [])
        if str(src) not in blocked
    ]


def is_english_language(value: object) -> bool:
    lang = str(value or "").strip().lower().replace("_", "-")
    if not lang:
        return False
    primary = lang.split("-", 1)[0]
    return lang in ENGLISH or primary in ENGLISH


def bazarr_key(data: dict[str, Any]) -> str:
    key = str((data.get("auth") or {}).get("apikey") or "").strip()
    if not key:
        raise RuntimeError("Bazarr API key missing from config.yaml")
    return key


def jellyfin_key(data: dict[str, Any]) -> str:
    key = str((data.get("jellyfin") or {}).get("apikey") or "").strip()
    if not key:
        raise RuntimeError("Jellyfin API key missing from Bazarr config")
    return key


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: object | None = None,
    timeout: int = 120,
) -> Any:
    payload = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode()
            if response.status in {204} or not raw:
                return None
            stripped = raw.lstrip()
            if not stripped.startswith(("{", "[")):
                return {"non_json": True, "preview": stripped[:120]}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"{method} {url} failed ({exc.code}): {detail}") from exc


def repair_english_profile() -> None:
    """Bazarr 1.6 matches cutoff to item id. A profile without ids crashes every search."""
    script = r"""
import json, sqlite3
conn = sqlite3.connect("/config/db/bazarr.db")
row = conn.execute(
    "SELECT items, cutoff FROM table_languages_profiles WHERE profileId = 1"
).fetchone()
if row is None:
    raise SystemExit("English profile id 1 is missing")
items = json.loads(row[0] or "[]")
changed = False
for index, item in enumerate(items, start=1):
    if item.get("id") != index:
        item["id"] = index
        changed = True
    for key in ("forced", "hi", "audio_only_include"):
        value = item.get(key)
        if value is True or value == "True":
            normalized = "True"
        else:
            normalized = "False"
        if item.get(key) != normalized:
            item[key] = normalized
            changed = True
    exclude = item.get("audio_exclude")
    if exclude is True or exclude == "True":
        normalized_exclude = "True"
    else:
        normalized_exclude = "False"
    if item.get("audio_exclude") != normalized_exclude:
        item["audio_exclude"] = normalized_exclude
        changed = True
cutoff = items[0]["id"] if items else None
if row[1] != cutoff:
    changed = True
if changed:
    conn.execute(
        "UPDATE table_languages_profiles SET items = ?, cutoff = ? WHERE profileId = 1",
        (json.dumps(items), cutoff),
    )
    conn.commit()
    print("repaired English profile")
else:
    print("English profile already valid")
"""
    subprocess.run(
        ["docker", "exec", "-i", "bazarr", "python3"],
        input=script,
        text=True,
        check=True,
    )


def assign_english_profiles() -> None:
    subprocess.check_call(
        [
            "docker",
            "exec",
            "bazarr",
            "python3",
            "-c",
            (
                "import sqlite3; c=sqlite3.connect('/config/db/bazarr.db'); "
                "c.execute('UPDATE table_shows SET profileId = 1 WHERE profileId IS NULL'); "
                "c.execute('UPDATE table_movies SET profileId = 1 WHERE profileId IS NULL'); "
                "c.commit()"
            ),
        ]
    )


def mark_embedded_only_as_missing() -> None:
    """Stop treating embedded PGS/text as satisfying the English profile."""
    script = r"""
import sqlite3
c = sqlite3.connect("/config/db/bazarr.db")
c.execute("DELETE FROM table_movies_subtitles WHERE path IS NULL OR path = ''")
c.execute("DELETE FROM table_episodes_subtitles WHERE path IS NULL OR path = ''")
missing = '["en"]'
c.execute(
    "UPDATE table_movies SET missing_subtitles = ? "
    "WHERE radarrId NOT IN (SELECT radarrId FROM table_movies_subtitles "
    "WHERE path LIKE '%.srt' OR path LIKE '%.vtt')",
    (missing,),
)
c.execute(
    "UPDATE table_episodes SET missing_subtitles = ? "
    "WHERE sonarrEpisodeId NOT IN (SELECT sonarrEpisodeId FROM table_episodes_subtitles "
    "WHERE path LIKE '%.srt' OR path LIKE '%.vtt')",
    (missing,),
)
c.commit()
print("cleared embedded-only subtitle rows")
"""
    subprocess.run(
        ["docker", "exec", "-i", "bazarr", "python3"],
        input=script,
        text=True,
        check=True,
    )


def restart_bazarr() -> None:
    subprocess.check_call(["docker", "restart", "bazarr"])
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BAZARR}/system/status", timeout=5)
            return
        except OSError:
            time.sleep(2)
    raise RuntimeError("Bazarr did not come back after restart")


def trigger_task(api_key: str, job_id: str) -> None:
    encoded = urllib.parse.quote(job_id)
    request_json(
        f"{BAZARR}/api/system/tasks?taskid={encoded}",
        method="POST",
        headers={"X-API-KEY": api_key},
        body={},
    )


def bazarr_path_to_windows(path: str) -> Path | None:
    path = path.strip().replace("\\", "/")
    if not path:
        return None
    lower = path.lower()
    for prefix in (
        "/app/sonarr/bin//media/video",
        "/app/sonarr/bin/media/video",
        "/app/radarr/bin//media/video",
        "/app/radarr/bin/media/video",
        "/media/video",
    ):
        if lower.startswith(prefix):
            rel = path[len(prefix) :].lstrip("/")
            return VIDEO_ROOT / rel.replace("/", "\\")
    if re.match(r"^[a-z]:/", lower) or re.match(r"^[a-z]:\\", path, flags=re.I):
        drive, rest = re.split(r"[:]", path, maxsplit=1)
        return Path(f"{drive.upper()}:{rest.replace('/', '\\')}")
    return None


def sidecar_paths_for_media(media_path: Path) -> list[Path]:
    base = media_path.stem
    parent = media_path.parent
    names = [
        f"{base}.en.srt",
        f"{base}.eng.srt",
        f"{base}.en.vtt",
        f"{base}.eng.vtt",
        f"{base}.srt",
        f"{base}.vtt",
    ]
    found: list[Path] = []
    for name in names:
        candidate = parent / name
        if candidate.is_file() and candidate.stat().st_size > 0:
            found.append(candidate)
    if parent.is_dir():
        stem_lower = base.lower()
        for candidate in parent.iterdir():
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                continue
            name = candidate.name.lower()
            if not name.endswith(SIDECAR_SUFFIXES):
                continue
            if name.startswith(f"{stem_lower}.en.") or name.startswith(f"{stem_lower}.eng."):
                found.append(candidate)
    return list(dict.fromkeys(found))


def has_english_sidecar_on_disk(path_field: str | None) -> bool:
    if not path_field:
        return False
    win = bazarr_path_to_windows(str(path_field))
    if not win or not win.is_file():
        return False
    return bool(sidecar_paths_for_media(win))


def _subtitle_is_sidecar(sub: dict[str, Any]) -> bool:
    path = str(sub.get("path") or "").lower()
    if not path:
        return False
    if sub.get("embedded") is True or sub.get("embedded_track_id") is not None:
        return False
    return path.endswith(SIDECAR_SUFFIXES)


def _subtitle_is_english_sidecar(sub: dict[str, Any]) -> bool:
    if not _subtitle_is_sidecar(sub):
        return False
    codes = [sub.get(key) for key in ("code2", "code3", "language") if sub.get(key)]
    if not codes:
        return True
    return any(is_english_language(code) for code in codes)


def movie_has_text_sub(movie: dict[str, Any]) -> bool:
    if has_english_sidecar_on_disk(str(movie.get("path") or "")):
        return True
    return any(_subtitle_is_english_sidecar(sub) for sub in movie.get("subtitles") or [])


def episode_has_text_sub(episode: dict[str, Any]) -> bool:
    if has_english_sidecar_on_disk(str(episode.get("path") or "")):
        return True
    return any(_subtitle_is_english_sidecar(sub) for sub in episode.get("subtitles") or [])


def iter_movies(api_key: str) -> list[dict[str, Any]]:
    payload = request_json(
        f"{BAZARR}/api/movies?start=0&length=-1",
        headers={"X-API-KEY": api_key},
    )
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    if isinstance(payload, list):
        return payload
    return []


def iter_series(api_key: str) -> list[dict[str, Any]]:
    payload = request_json(
        f"{BAZARR}/api/series",
        headers={"X-API-KEY": api_key},
    )
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    if isinstance(payload, list):
        return payload
    return []


def iter_episodes(api_key: str, series_id: int) -> list[dict[str, Any]]:
    payload = request_json(
        f"{BAZARR}/api/episodes?seriesid[]={series_id}",
        headers={"X-API-KEY": api_key},
    )
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            return data
    if isinstance(payload, list):
        return payload
    return []


def download_first_english_movie(api_key: str, movie: dict[str, Any]) -> str:
    radarr_id = movie.get("radarrId") or movie.get("radarrid")
    if not radarr_id:
        return "no-radarr-id"
    headers = {"X-API-KEY": api_key}
    search_error = ""
    try:
        results = request_json(
            f"{BAZARR}/api/providers/movies?radarrid={int(radarr_id)}",
            headers=headers,
            timeout=180,
        )
    except RuntimeError as exc:
        results = None
        search_error = str(exc)

    rows = results.get("data") if isinstance(results, dict) else results
    if isinstance(rows, list):
        for row in rows:
            language = str(row.get("language") or row.get("code2") or "")
            if not is_english_language(language):
                continue
            provider = urllib.parse.quote(str(row.get("provider") or ""))
            subtitle = urllib.parse.quote(str(row.get("subtitle") or row.get("id") or ""), safe="")
            if not provider or not subtitle:
                continue
            try:
                request_json(
                    (
                        f"{BAZARR}/api/providers/movies?radarrid={int(radarr_id)}"
                        f"&hi=False&forced=False&original_format=False"
                        f"&provider={provider}&subtitle={subtitle}"
                    ),
                    method="POST",
                    headers=headers,
                    timeout=180,
                )
                return f"downloaded:{row.get('provider')}"
            except RuntimeError as exc:
                return f"download-failed:{exc}"

    try:
        request_json(
            f"{BAZARR}/api/movies?radarrid={int(radarr_id)}&action=search-missing",
            method="PATCH",
            headers=headers,
        )
        if search_error:
            return f"search-missing-queued ({search_error})"
        return "search-missing-queued"
    except RuntimeError as exc:
        return f"search-missing-failed:{exc}"


def download_first_english_episode(
    api_key: str, series_id: int, episode: dict[str, Any]
) -> str:
    episode_id = episode.get("sonarrEpisodeId") or episode.get("episodeId") or episode.get("id")
    if not episode_id:
        return "no-episode-id"
    headers = {"X-API-KEY": api_key}
    search_error = ""
    try:
        results = request_json(
            f"{BAZARR}/api/providers/episodes?seriesid={int(series_id)}&episodeid={int(episode_id)}",
            headers=headers,
            timeout=180,
        )
    except RuntimeError as exc:
        results = None
        search_error = str(exc)

    rows = results.get("data") if isinstance(results, dict) else results
    if isinstance(rows, list):
        for row in rows:
            language = str(row.get("language") or row.get("code2") or "")
            if not is_english_language(language):
                continue
            provider = urllib.parse.quote(str(row.get("provider") or ""))
            subtitle = urllib.parse.quote(str(row.get("subtitle") or row.get("id") or ""), safe="")
            if not provider or not subtitle:
                continue
            try:
                request_json(
                    (
                        f"{BAZARR}/api/providers/episodes?seriesid={int(series_id)}"
                        f"&episodeid={int(episode_id)}"
                        f"&hi=False&forced=False&original_format=False"
                        f"&provider={provider}&subtitle={subtitle}"
                    ),
                    method="POST",
                    headers=headers,
                    timeout=180,
                )
                return f"downloaded:{row.get('provider')}"
            except RuntimeError as exc:
                return f"download-failed:{exc}"

    try:
        request_json(
            f"{BAZARR}/api/series?seriesid={int(series_id)}&action=search-missing",
            method="PATCH",
            headers=headers,
        )
        if search_error:
            return f"search-missing-queued ({search_error})"
        return "search-missing-queued"
    except RuntimeError as exc:
        return f"search-missing-failed:{exc}"


def refresh_jellyfin_item(api_key: str, title: str) -> None:
    query = urllib.parse.urlencode(
        {
            "searchTerm": title,
            "includeItemTypes": "Movie",
            "recursive": "true",
            "limit": "5",
        }
    )
    payload = request_json(
        f"{JELLYFIN}/Items?{query}",
        headers={"X-Emby-Token": api_key},
    )
    items = (payload or {}).get("Items") if isinstance(payload, dict) else []
    for item in items or []:
        item_id = item.get("Id")
        if not item_id:
            continue
        request_json(
            f"{JELLYFIN}/Items/{item_id}/Refresh?Recursive=true&MetadataRefreshMode=ValidationOnly&ImageRefreshMode=None&ReplaceAllMetadata=false",
            method="POST",
            headers={"X-Emby-Token": api_key},
            body={},
        )


def queue_search_missing(api_key: str) -> tuple[int, int]:
    """Ask Bazarr to search every movie/series that still lacks a sidecar SRT."""
    headers = {"X-API-KEY": api_key}
    movies_queued = 0
    series_queued = 0
    for movie in iter_movies(api_key):
        if movie_has_text_sub(movie):
            continue
        radarr_id = movie.get("radarrId") or movie.get("radarrid")
        if not radarr_id:
            continue
        try:
            request_json(
                f"{BAZARR}/api/movies?radarrid={int(radarr_id)}&action=search-missing",
                method="PATCH",
                headers=headers,
            )
            movies_queued += 1
        except RuntimeError as exc:
            print(f"movie queue failed {movie.get('title')}: {exc}")
    for show in iter_series(api_key):
        series_id = show.get("sonarrSeriesId") or show.get("seriesId") or show.get("id")
        if not series_id:
            continue
        try:
            request_json(
                f"{BAZARR}/api/series?seriesid={int(series_id)}&action=search-missing",
                method="PATCH",
                headers=headers,
            )
            series_queued += 1
        except RuntimeError as exc:
            print(f"series queue failed {show.get('title')}: {exc}")
    return movies_queued, series_queued


def _is_skipped_media(path_field: str | None) -> bool:
    win = bazarr_path_to_windows(str(path_field or ""))
    if not win:
        return False
    return str(win) in SKIP_WINDOWS_PATHS


def fill_missing_subtitles(api_key: str, *, batch: int = FILL_MISSING_BATCH) -> tuple[int, int]:
    """Return (attempted, still_missing_movies). batch<=0 means all titles."""
    movies = iter_movies(api_key)
    missing_movies = [
        m
        for m in movies
        if not movie_has_text_sub(m) and not _is_skipped_media(str(m.get("path") or ""))
    ]
    limit = len(missing_movies) if batch <= 0 else batch
    attempted = 0
    for movie in missing_movies[:limit]:
        title = str(movie.get("title") or "unknown")
        status = download_first_english_movie(api_key, movie)
        print(f"movie {title}: {status}")
        attempted += 1
        time.sleep(0.25)

    series_list = iter_series(api_key)
    episode_budget = None if batch <= 0 else max(0, batch - attempted)
    ep_attempted = 0
    for show in series_list:
        if episode_budget is not None and ep_attempted >= episode_budget:
            break
        series_id = show.get("sonarrSeriesId") or show.get("seriesId") or show.get("id")
        if not series_id:
            continue
        episodes = iter_episodes(api_key, int(series_id))
        for ep in episodes:
            if episode_budget is not None and ep_attempted >= episode_budget:
                break
            if episode_has_text_sub(ep) or _is_skipped_media(str(ep.get("path") or "")):
                continue
            label = str(ep.get("title") or ep.get("path") or "episode")
            status = download_first_english_episode(api_key, int(series_id), ep)
            print(f"episode {label}: {status}")
            ep_attempted += 1
            time.sleep(0.25)

    movies_after = iter_movies(api_key)
    still_missing = len([m for m in movies_after if not movie_has_text_sub(m)])
    return attempted + ep_attempted, still_missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensure Bazarr fetches English SRTs")
    parser.add_argument("--title", action="append", default=[], help="Movie title to search immediately")
    parser.add_argument("--skip-restart", action="store_true")
    parser.add_argument("--skip-jellyfin", action="store_true", help="Do not refresh Jellyfin items")
    parser.add_argument("--fill-missing", action="store_true", help="Provider search for titles without English SRT")
    parser.add_argument("--fill-batch", type=int, default=FILL_MISSING_BATCH)
    args = parser.parse_args()

    data = load_config()
    changed = apply_policy(data)
    if changed:
        BAZARR_CFG.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
        print("Updated Bazarr policy: ignore PGS/VobSub; keep searching English SRTs")
        if not args.skip_restart:
            restart_bazarr()
            print("Restarted Bazarr")
    else:
        print("Bazarr already ignores image subtitles")

    api_key = bazarr_key(data)
    repair_english_profile()
    assign_english_profiles()
    print("Assigned English profile to movies/shows missing one")
    mark_embedded_only_as_missing()

    for job_id in (
        "update_movies",
        "movies_full_scan_subtitles",
        "series_full_scan_subtitles",
        "wanted_search_missing_subtitles_movies",
        "wanted_search_missing_subtitles_series",
    ):
        try:
            trigger_task(api_key, job_id)
            print(f"Triggered Bazarr task: {job_id}")
        except RuntimeError as exc:
            print(f"Task {job_id} skipped: {exc}")
        time.sleep(1)

    movies = iter_movies(api_key)
    missing = [movie for movie in movies if not movie_has_text_sub(movie)]
    print(f"Bazarr movies={len(movies)} missing_text_subs={len(missing)}")

    titles = [title.lower() for title in args.title]
    targets = [
        movie
        for movie in movies
        if any(title in str(movie.get("title") or "").lower() for title in titles)
    ]
    for movie in targets:
        status = download_first_english_movie(api_key, movie)
        print(f"{movie.get('title')}: {status}")
        if not args.skip_jellyfin:
            try:
                refresh_jellyfin_item(jellyfin_key(data), str(movie.get("title") or ""))
                print(f"{movie.get('title')}: jellyfin refresh queued")
            except RuntimeError as exc:
                print(f"{movie.get('title')}: jellyfin refresh skipped ({exc})")

    if args.fill_missing:
        movies_queued, series_queued = queue_search_missing(api_key)
        print(f"queued search-missing movies={movies_queued} series={series_queued}")
        attempted, still_missing = fill_missing_subtitles(api_key, batch=args.fill_batch)
        print(f"fill-missing attempted={attempted} movies_still_missing={still_missing}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Fix Stargate SG-1 / Atlantis season metadata and artwork in Jellyfin."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(r"C:\ProgramData\Jellyfin\Server\data\jellyfin.db")
API_KEY_PATH = Path(r"C:\ProgramData\mediapc-stack\jellyfin-api.key")
JELLYFIN_BASE = "http://127.0.0.1:8096"
TV_ROOT = Path(r"E:\Video\TV SHOWS")

SHOWS = [
    {
        "label": "Stargate SG-1",
        "item_id": "E2687798-BDB0-B4FC-FBEB-1D643C64DCC3",
        "old_folder": TV_ROOT
        / "Stargate SG-1 (1994) Season 1-10 S01-10 (1080p BluRay x265 HEVC 10bit DD 5.1 EDGE2020)",
        "new_folder": TV_ROOT / "Stargate SG-1 (1997) [tvdbid-72449]",
        "display_name": "Stargate SG-1",
        "production_year": 1997,
        "providers": {
            "Tvdb": "72449",
            "Tmdb": "4629",
            "Imdb": "tt0118480",
            "TvdbSlug": "stargate-sg-1",
        },
        "rename_folder": True,
    },
    {
        "label": "Stargate Atlantis",
        "item_id": "1C73562E-DC44-E249-25D2-D194A8F30801",
        "old_folder": TV_ROOT
        / "Stargate Atlantis (2004) Season 1-5 S01-05 (1080p BluRay x265 HEVC 10bit DDP 5.1 EDGE2020)",
        "new_folder": TV_ROOT / "Stargate Atlantis (2004) [tvdbid-70851]",
        "display_name": "Stargate Atlantis",
        "production_year": 2004,
        "providers": {
            "Tvdb": "70851",
            "Tmdb": "2290",
            "Imdb": "tt0374455",
            "TvdbSlug": "stargate-atlantis",
        },
        "rename_folder": True,
    },
]


def normalize_guid(value: str) -> str:
    return value.replace("-", "").lower()


def stop_jellyfin() -> None:
    for name in ("jellyfin", "Jellyfin.Windows.Tray"):
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"Stop-Process -Name {name} -Force -ErrorAction SilentlyContinue"],
            check=False,
        )
    time.sleep(3)


def start_jellyfin() -> None:
    tray = Path(r"C:\Program Files\Jellyfin\Server\jellyfin-windows-tray\Jellyfin.Windows.Tray.exe")
    if tray.exists():
        subprocess.Popen([str(tray)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(8)


def backup_db(backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    dest = backup_dir / f"jellyfin.db.{stamp}.bak"
    shutil.copy2(DB_PATH, dest)
    return dest


def update_paths(conn: sqlite3.Connection, old_prefix: str, new_prefix: str) -> int:
    cur = conn.cursor()
    rows = cur.execute(
        "SELECT Id, Path FROM BaseItems WHERE Path LIKE ?",
        (old_prefix.replace("\\", "\\\\") + "%",),
    ).fetchall()
    count = 0
    for item_id, path in rows:
        if not path:
            continue
        new_path = new_prefix + path[len(old_prefix) :]
        cur.execute("UPDATE BaseItems SET Path = ? WHERE Id = ?", (new_path, item_id))
        count += 1
    return count


def upsert_providers(conn: sqlite3.Connection, item_id: str, providers: dict[str, str]) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM BaseItemProviders WHERE ItemId = ?", (item_id,))
    for provider_id, provider_value in providers.items():
        cur.execute(
            "INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue) VALUES (?, ?, ?)",
            (item_id, provider_id, provider_value),
        )


def update_series_row(
    conn: sqlite3.Connection,
    item_id: str,
    name: str,
    production_year: int,
    old_prefix: str,
    new_prefix: str,
) -> None:
    conn.execute(
        """
        UPDATE BaseItems
        SET Name = ?, ProductionYear = ?, Path = ?, SeriesName = ?, ForcedSortName = NULL
        WHERE Id = ?
        """,
        (name, production_year, new_prefix, name, item_id),
    )
    conn.execute(
        "UPDATE BaseItems SET SeriesName = ? WHERE SeriesId = ?",
        (name, item_id),
    )
    conn.execute(
        "UPDATE BaseItems SET Path = REPLACE(Path, ?, ?) WHERE Path LIKE ?",
        (old_prefix, new_prefix, old_prefix + "%"),
    )


def api_post(path: str) -> None:
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
    req = urllib.request.Request(
        JELLYFIN_BASE + path,
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Unexpected status {resp.status} for POST {path}")


def refresh_show(item_id: str) -> None:
    qs = urllib.parse.urlencode(
        {
            "Recursive": "true",
            "MetadataRefreshMode": "FullRefresh",
            "ImageRefreshMode": "FullRefresh",
            "ReplaceAllMetadata": "true",
            "ReplaceAllImages": "true",
        }
    )
    api_post(f"/Items/{normalize_guid(item_id)}/Refresh?{qs}")


def summarize(item_id: str, label: str) -> None:
    api_key = API_KEY_PATH.read_text(encoding="utf-8").strip()
    uid_req = urllib.request.Request(
        f"{JELLYFIN_BASE}/Users",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(uid_req, timeout=30) as resp:
        users = json.loads(resp.read().decode("utf-8"))
    user_id = normalize_guid(users[0]["Id"])
    item_guid = normalize_guid(item_id)

    item_req = urllib.request.Request(
        f"{JELLYFIN_BASE}/Users/{user_id}/Items/{item_guid}",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(item_req, timeout=30) as resp:
        item = json.loads(resp.read().decode("utf-8"))

    children_req = urllib.request.Request(
        f"{JELLYFIN_BASE}/Users/{user_id}/Items/{item_guid}/Children?"
        + urllib.parse.urlencode({"IncludeItemTypes": "Season", "Fields": "Overview,ImageTags,ProviderIds,ChildCount"}),
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(children_req, timeout=30) as resp:
        seasons = json.loads(resp.read().decode("utf-8")).get("Items") or []

    print(f"\n{label}:")
    print(f"  name={item.get('Name')}")
    print(f"  images={list((item.get('ImageTags') or {}).keys())}")
    print(f"  providerIds={item.get('ProviderIds')}")
    for season in seasons:
        idx = season.get("IndexNumber")
        imgs = list((season.get("ImageTags") or {}).keys())
        print(f"  season {idx}: images={imgs} episodes={season.get('ChildCount')}")


def remove_empty_unknown_seasons(conn: sqlite3.Connection, item_id: str) -> int:
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT Id FROM BaseItems
        WHERE ParentId = ?
          AND Type LIKE '%Season%'
          AND (IndexNumber IS NULL OR Name = 'Season Unknown')
        """,
        (item_id,),
    ).fetchall()
    removed = 0
    for (season_id,) in rows:
        ep_count = cur.execute(
            "SELECT COUNT(*) FROM BaseItems WHERE ParentId = ?", (season_id,)
        ).fetchone()[0]
        if ep_count:
            continue
        for table, column in [
            ("UserData", "ItemId"),
            ("AncestorIds", "ItemId"),
            ("AncestorIds", "ParentItemId"),
            ("BaseItemProviders", "ItemId"),
            ("BaseItemMetadataFields", "ItemId"),
            ("BaseItemTrailerTypes", "ItemId"),
            ("ItemValuesMap", "ItemId"),
            ("MediaStreamInfos", "ItemId"),
            ("BaseItemImageInfos", "ItemId"),
        ]:
            cur.execute(f"DELETE FROM {table} WHERE {column} = ?", (season_id,))
        cur.execute("DELETE FROM BaseItems WHERE Id = ?", (season_id,))
        removed += 1
        print(f"Removed empty season {season_id}")
    return removed


def repair_show(conn: sqlite3.Connection, show: dict, dry_run: bool) -> None:
    old_folder = str(show["old_folder"])
    new_folder = str(show["new_folder"])
    item_id = show["item_id"]
    label = show["label"]

    print(f"\n=== {label} ===")
    if not show["old_folder"].exists():
        if show["new_folder"].exists():
            print("Already renamed:", new_folder)
            old_folder = new_folder
        else:
            raise FileNotFoundError(f"Missing show folder: {old_folder}")

    if dry_run:
        print(f"Would rename: {old_folder} -> {new_folder}")
        print(f"Would set providers: {show['providers']}")
        return

    if show["rename_folder"] and show["old_folder"].exists() and old_folder != new_folder:
        if show["new_folder"].exists():
            raise FileExistsError(f"Target folder already exists: {new_folder}")
        show["old_folder"].rename(show["new_folder"])
        print(f"Renamed folder -> {new_folder}")

    upsert_providers(conn, item_id, show["providers"])
    update_series_row(
        conn,
        item_id,
        show["display_name"],
        show["production_year"],
        old_folder,
        new_folder,
    )
    print(f"Updated providers and paths for {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-refresh", action="store_true")
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()

    backup_dir = Path(r"C:\ProgramData\Jellyfin\backups\stargate-metadata")
    if not args.dry_run:
        backup = backup_db(backup_dir)
        print(f"Database backup: {backup}")
        stop_jellyfin()

    conn = sqlite3.connect(DB_PATH)
    try:
        if not args.cleanup_only:
            for show in SHOWS:
                repair_show(conn, show, args.dry_run)
        if not args.dry_run:
            for show in SHOWS:
                removed = remove_empty_unknown_seasons(conn, show["item_id"])
                if removed:
                    print(f"Cleaned {removed} empty season(s) for {show['label']}")
            conn.commit()
    finally:
        conn.close()

    if args.dry_run:
        return 0

    start_jellyfin()

    if args.cleanup_only or args.skip_refresh:
        return 0

    print("\nRefreshing metadata...")
    for show in SHOWS:
        refresh_show(show["item_id"])
    print("Metadata refresh queued.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

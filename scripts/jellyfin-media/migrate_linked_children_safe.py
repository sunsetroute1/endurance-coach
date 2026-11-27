#!/usr/bin/env python3
"""Migrate Jellyfin 10.x linked-child JSON without RC7's stale-file cleanup."""

from __future__ import annotations

import argparse
import json
import sqlite3
import uuid
from pathlib import Path, PureWindowsPath


CONTAINER_TYPES = {
    "MediaBrowser.Controller.Entities.Movies.BoxSet",
    "MediaBrowser.Controller.Playlists.Playlist",
    "MediaBrowser.Controller.Entities.CollectionFolder",
}
VIDEO_TYPES = {
    "MediaBrowser.Controller.Entities.Video",
    "MediaBrowser.Controller.Entities.Movies.Movie",
    "MediaBrowser.Controller.Entities.TV.Episode",
}
PLAYLIST_TYPE = "MediaBrowser.Controller.Playlists.Playlist"

CHILD_TYPE = {
    "Manual": 0,
    "Shortcut": 1,
    "LocalAlternateVersion": 2,
    "LinkedAlternateVersion": 3,
}


def normalize_guid(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return str(uuid.UUID(value)).upper()
    except ValueError:
        return None


def child_type(value: object, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return CHILD_TYPE.get(value, default)
    return default


def absolute_child_path(containing_folder_path: str | None, child_path: str) -> str | None:
    path = PureWindowsPath(child_path)
    if path.is_absolute():
        return str(path)
    if not containing_folder_path:
        return None
    return str(PureWindowsPath(containing_folder_path) / path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.db.is_file():
        raise SystemExit(f"Database not found: {args.db}")

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        existing_foreign_key_errors = set(conn.execute("PRAGMA foreign_key_check"))
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='LinkedChildren'"
        ).fetchone():
            raise SystemExit("LinkedChildren table does not exist; run schema migrations first")

        items = conn.execute(
            """
            SELECT Id, Data, Type, Path, IsFolder
            FROM BaseItems
            WHERE Data IS NOT NULL
              AND Type IN (?, ?, ?, ?, ?, ?)
            """,
            tuple(CONTAINER_TYPES | VIDEO_TYPES),
        ).fetchall()
        all_ids = {row[0] for row in conn.execute("SELECT Id FROM BaseItems")}
        path_to_id = {
            path.casefold(): item_id
            for item_id, path in conn.execute(
                "SELECT Id, Path FROM BaseItems WHERE Path IS NOT NULL"
            )
        }
        existing = {
            (parent_id, child_id, sort_order)
            for parent_id, child_id, sort_order in conn.execute(
                "SELECT ParentId, ChildId, SortOrder FROM LinkedChildren"
            )
        }
        populated_playlists = {
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT lc.ParentId
                FROM LinkedChildren lc
                JOIN BaseItems b ON b.Id = lc.ParentId
                WHERE b.Type = ?
                """,
                (PLAYLIST_TYPE,),
            )
        }

        candidates: list[tuple[str, str, int, int]] = []
        dropped = 0

        def resolve(
            entry: dict[str, object], containing_folder_path: str | None
        ) -> str | None:
            for key in ("ItemId",):
                item_id = normalize_guid(entry.get(key))
                if item_id in all_ids:
                    return item_id

            raw_path = entry.get("Path")
            if isinstance(raw_path, str) and raw_path:
                direct = path_to_id.get(raw_path.casefold())
                if direct:
                    return direct
                absolute = absolute_child_path(containing_folder_path, raw_path)
                if absolute:
                    resolved = path_to_id.get(absolute.casefold())
                    if resolved:
                        return resolved

            library_item_id = normalize_guid(entry.get("LibraryItemId"))
            return library_item_id if library_item_id in all_ids else None

        for parent_id, raw_data, item_type, item_path, is_folder in items:
            try:
                data = json.loads(raw_data)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue

            sort_order = 0
            if item_type in VIDEO_TYPES:
                for raw_path in data.get("LocalAlternateVersions", []):
                    if not isinstance(raw_path, str):
                        continue
                    child_id = path_to_id.get(raw_path.casefold())
                    if child_id:
                        candidates.append(
                            (
                                parent_id,
                                child_id,
                                CHILD_TYPE["LocalAlternateVersion"],
                                sort_order,
                            )
                        )
                        sort_order += 1

                for entry in data.get("LinkedAlternateVersions", []):
                    if not isinstance(entry, dict):
                        continue
                    child_id = resolve(entry, None)
                    if child_id:
                        candidates.append(
                            (
                                parent_id,
                                child_id,
                                CHILD_TYPE["LinkedAlternateVersion"],
                                sort_order,
                            )
                        )
                        sort_order += 1

            linked_children = data.get("LinkedChildren", [])
            if not isinstance(linked_children, list):
                continue
            container_path = (
                item_path
                if is_folder
                else str(PureWindowsPath(item_path).parent) if item_path else None
            )
            for entry in linked_children:
                if not isinstance(entry, dict):
                    continue
                child_id = resolve(entry, container_path)
                if not child_id:
                    dropped += 1
                    continue
                candidates.append(
                    (
                        parent_id,
                        child_id,
                        child_type(entry.get("Type")),
                        sort_order,
                    )
                )
                sort_order += 1

        inserted = 0
        seen_non_playlist: set[tuple[str, str]] = set()
        for parent_id, child_id, kind, sort_order in sorted(
            candidates,
            key=lambda row: (
                row[0],
                row[3],
                0 if row[2] == CHILD_TYPE["LocalAlternateVersion"] else 1,
            ),
        ):
            is_playlist = conn.execute(
                "SELECT Type = ? FROM BaseItems WHERE Id = ?",
                (PLAYLIST_TYPE, parent_id),
            ).fetchone()
            if is_playlist and is_playlist[0]:
                if parent_id in populated_playlists:
                    continue
            else:
                pair = (parent_id, child_id)
                if pair in seen_non_playlist:
                    continue
                seen_non_playlist.add(pair)

            key = (parent_id, child_id, sort_order)
            if key in existing:
                continue
            conn.execute(
                """
                INSERT INTO LinkedChildren (ParentId, ChildId, ChildType, SortOrder)
                VALUES (?, ?, ?, ?)
                """,
                (parent_id, child_id, kind, sort_order),
            )
            existing.add(key)
            inserted += 1

        if args.dry_run:
            conn.rollback()
        else:
            foreign_key_errors = set(conn.execute("PRAGMA foreign_key_check"))
            new_foreign_key_errors = foreign_key_errors - existing_foreign_key_errors
            if new_foreign_key_errors:
                raise RuntimeError(
                    "Migration introduced foreign-key errors: "
                    f"{list(new_foreign_key_errors)[:10]}"
                )
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError(f"Database integrity check failed: {integrity}")
            conn.commit()
        print(
            f"processed={len(items)} candidates={len(candidates)} "
            f"inserted={inserted} dropped={dropped} "
            f"preexisting_fk_errors={len(existing_foreign_key_errors)} "
            f"dry_run={args.dry_run}"
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

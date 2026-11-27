#!/usr/bin/env python3
"""Repair Jellyfin library duplicates and Alien collection metadata."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ALIEN_TMDB_COLLECTION = "8091"
WRONG_ALIEN_TMDB = "1431554"

ALIEN_CORE_PATHS = [
    r"E:\Video\MOVIES\Action, sci-fi, etc\Alien Anthology\Alien (1979) DC  [2160p x265 10bit Joy]\Alien (1979) DC  [2160p x265 10bit S91 Joy].mkv",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Alien Anthology\Aliens.1986.Special.Edition.UHD.BluRay.2160p.TrueHD.Atmos.7.1.DV.HEVC.REMUX-FraMeSToR.mkv",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Alien Anthology\Alien.3.1992.Special.Assembly.Cut.BluRay.2160p.Ai.MULTi.DTS-HD.MA.5.1.DDP.H265-KC\alien.3.1992.special.assembly.cut.v2.4k-kc.mkv",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Alien Anthology\Alien Resurrection 1997 Ai UHD BluRay 2160p SDR HEVC DTS-HD MA 5.1 x265-E\Alien Resurrection 1997.mkv",
]

# Keep the best encode; remove duplicate movie rows at these paths.
REMOVE_MOVIE_PATHS = {
    r"E:\Video\MOVIES\Action, sci-fi, etc\Black.Sheep.1996.BRRIP.X264.AAC.CrEwSaDe\Black.Sheep.1996.BRRIP.X264.AAC.CrEwSaDe.mkv",
    r"E:\Video\MOVIES\Comedy\Black Sheep 1996 Remastered 1080p BluRay HEVC x265 5.1 BONE.mkv",
    r"E:\Video\MOVIES\Action, sci-fi, etc\The Book of Eli (2010) [1080p]\The.Book.of.Eli.2010.1080p.BrRip.x264.YIFY.mp4",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Cast Away (2000) [1080p]\Cast.Away.2000.1080p.BrRip.x264.YIFY.mp4",
    r"E:\Video\MOVIES\Drama\Drunktown's Finest (2014)\Drunktown's Finest 2014 Eng & Spa Audio.mp4",
    r"E:\Video\MOVIES\Comedy\Fear of a Black Hat\fear.of.a.black.hat.1994.dvdrip.xvid-vh-prod.mp4",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Hacksaw Ridge 2016 HDCAM x264 AC3-TuttyFruity\Hacksaw Ridge 2016 HDCAM x264 AC3-TuttyFruity.mkv",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Hancock (2008) [1080p]\Hancock.2008.1080p.BluRay.x264.YIFY.mp4",
    r"E:\Video\MOVIES\Action, sci-fi, etc\Hardcore Henry 2015 1080p BluRay x264 DTS-JYK.mp4",
    r"E:\Video\MOVIES\Comedy\Run Ronnie Run\Run Ronnie Run [2002].mp4",
    r"E:\Video\MOVIES\Comedy\Dumb.and.Dumber.1994.RERIP.Unrated.Bluray.1080p.DTS-HD.x264-Grym\Dumb.and.Dumber.Extras-Grym\Extras-Grym.mkv",
}

STAND_PARTS = [
    (
        r"E:\Video\MOVIES\Action, sci-fi, etc\Stephen King's The Stand (1994) Special Edition H264 AAC V3nDetta {PURE RG}\The Stand (1994) part2 Special Edition DVDrip H264 AAC V3nDetta {PURE RG}.mp4",
        "The Stand",
        "2",
    ),
    (
        r"E:\Video\MOVIES\Action, sci-fi, etc\Stephen King's The Stand (1994) Special Edition H264 AAC V3nDetta {PURE RG}\The Stand (1994) part3 Special Edition DVDrip H264 AAC V3nDetta {PURE RG}.mp4",
        "The Stand",
        "3",
    ),
    (
        r"E:\Video\MOVIES\Action, sci-fi, etc\Stephen King's The Stand (1994) Special Edition H264 AAC V3nDetta {PURE RG}\The Stand (1994) part4 Special Edition DVDrip H264 AAC V3nDetta {PURE RG}.mp4",
        "The Stand",
        "4",
    ),
]

ITEM_ID_TABLES = [
    ("UserData", "ItemId"),
    ("AncestorIds", "ItemId"),
    ("AncestorIds", "ParentItemId"),
    ("BaseItemProviders", "ItemId"),
    ("BaseItemMetadataFields", "ItemId"),
    ("BaseItemTrailerTypes", "ItemId"),
    ("ItemValuesMap", "ItemId"),
    ("MediaStreamInfos", "ItemId"),
    ("Chapters2", "ItemId"),
    ("MediaSegments", "ItemId"),
    ("LinkedChildren", "ItemId"),
    ("LinkedChildren", "LinkedChildId"),
    ("PeopleBaseItemMap", "ItemId"),
    ("PeopleBaseItemMap", "PeopleId"),
]

TYPE_RANK = {
    "MediaBrowser.Controller.Entities.TV.Episode": 0,
    "MediaBrowser.Controller.Entities.Movies.Movie": 0,
    "MediaBrowser.Controller.Entities.TV.Series": 0,
    "MediaBrowser.Controller.Entities.Movies.BoxSet": 0,
    "MediaBrowser.Controller.Entities.Video": 9,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def delete_item(conn: sqlite3.Connection, item_id: str, dry_run: bool) -> None:
    for table, column in ITEM_ID_TABLES:
        if not table_exists(conn, table):
            continue
        count = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column}=?",
            (item_id,),
        ).fetchone()[0]
        if count:
            log(f"  delete {count} row(s) from {table}.{column}")
            if not dry_run:
                conn.execute(f"DELETE FROM {table} WHERE {column}=?", (item_id,))

    row = conn.execute(
        "SELECT Name, Path, Type FROM BaseItems WHERE Id=?",
        (item_id,),
    ).fetchone()
    if row:
        log(f"  delete BaseItem {item_id}: {row}")
        if not dry_run:
            conn.execute("DELETE FROM BaseItems WHERE Id=?", (item_id,))


def choose_keep_row(rows: list[tuple]) -> tuple:
    return sorted(rows, key=lambda r: (TYPE_RANK.get(r[2], 5), r[1]))[0]


def remove_duplicate_paths(conn: sqlite3.Connection, dry_run: bool) -> int:
    removed = 0
    dup_paths = conn.execute(
        """
        SELECT Path, COUNT(*) cnt
        FROM BaseItems
        WHERE Path IS NOT NULL AND Path != ''
          AND Path NOT LIKE '%MetadataPath%'
        GROUP BY Path
        HAVING cnt > 1
        """
    ).fetchall()

    for path, _ in dup_paths:
        rows = conn.execute(
            "SELECT Id, Name, Type FROM BaseItems WHERE Path=?",
            (path,),
        ).fetchall()
        keep = choose_keep_row(rows)
        for row in rows:
            if row[0] == keep[0]:
                continue
            log(f"Duplicate path cleanup: keep {keep[0]} ({keep[2]}), remove {row[0]} ({row[2]})")
            delete_item(conn, row[0], dry_run)
            removed += 1
    return removed


def remove_movie_paths(conn: sqlite3.Connection, dry_run: bool) -> int:
    removed = 0
    for path in REMOVE_MOVIE_PATHS:
        rows = conn.execute(
            "SELECT Id, Name, Type FROM BaseItems WHERE Path=?",
            (path,),
        ).fetchall()
        for row in rows:
            log(f"Removing duplicate/inferior movie: {row[1]} | {path}")
            delete_item(conn, row[0], dry_run)
            removed += 1
    return removed


def fix_stand_parts(conn: sqlite3.Connection, dry_run: bool) -> int:
    fixed = 0
    for path, name, part in STAND_PARTS:
        rows = conn.execute(
            "SELECT Id FROM BaseItems WHERE Path=?",
            (path,),
        ).fetchall()
        for (item_id,) in rows:
            log(f"Fixing misidentified Stand by Me -> {name} (part {part})")
            if not dry_run:
                conn.execute(
                    "UPDATE BaseItems SET Name=?, SeriesName=?, IndexNumber=? WHERE Id=?",
                    (name, name, int(part), item_id),
                )
                conn.execute(
                    "DELETE FROM BaseItemProviders WHERE ItemId=? AND ProviderId='Tmdb' AND ProviderValue='235'",
                    (item_id,),
                )
                exists = conn.execute(
                    "SELECT 1 FROM BaseItemProviders WHERE ItemId=? AND ProviderId='Tmdb'",
                    (item_id,),
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue) VALUES (?, 'Tmdb', '13519')",
                        (item_id,),
                    )
            fixed += 1
    return fixed


def fix_alien_three_title(conn: sqlite3.Connection, dry_run: bool) -> int:
    path = ALIEN_CORE_PATHS[2]
    rows = conn.execute(
        "SELECT Id, Name FROM BaseItems WHERE Path=?",
        (path,),
    ).fetchall()
    for item_id, name in rows:
        if name.startswith("Alien") and name != "Alien\u00b3":
            log(f"Fixing Alien 3 title: {name!r} -> Alien\u00b3")
            if not dry_run:
                conn.execute(
                    "UPDATE BaseItems SET Name=? WHERE Id=?",
                    ("Alien\u00b3", item_id),
                )
            return 1
    return 0


def write_alien_collection_xml(collection_xml: Path, dry_run: bool) -> None:
    overview = (
        "The original Ellen Ripley saga: Alien (1979), Aliens (1986), Alien\u00b3 (1992), "
        "and Alien: Resurrection (1997)."
    )
    if dry_run:
        log(f"Would rewrite {collection_xml} with TMDb {ALIEN_TMDB_COLLECTION} and 4 core films")
        return

    root = ET.Element("Item")
    ET.SubElement(root, "ContentRating").text = "R"
    ET.SubElement(root, "Added").text = datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M:%S")
    ET.SubElement(root, "LockData").text = "true"
    ET.SubElement(root, "Overview").text = overview
    ET.SubElement(root, "LocalTitle").text = "Alien Collection"
    ET.SubElement(root, "PremiereDate").text = "1979-05-25"
    ET.SubElement(root, "DisplayOrder").text = "PremiereDate"
    ET.SubElement(root, "ProductionYear").text = "1979"
    ET.SubElement(root, "TmdbId").text = ALIEN_TMDB_COLLECTION

    genres = ET.SubElement(root, "Genres")
    for genre in ("Horror", "Action", "Thriller", "Science Fiction"):
        g = ET.SubElement(genres, "Genre")
        g.text = genre

    studios = ET.SubElement(root, "Studios")
    for studio in ("20th Century Fox", "Brandywine Productions"):
        s = ET.SubElement(studios, "Studio")
        s.text = studio

    items = ET.SubElement(root, "CollectionItems")
    for movie_path in ALIEN_CORE_PATHS:
        item = ET.SubElement(items, "CollectionItem")
        ET.SubElement(item, "Path").text = movie_path

    tree = ET.ElementTree(root)
    if collection_xml.exists():
        backup = collection_xml.with_suffix(".xml.bak")
        shutil.copy2(collection_xml, backup)
        log(f"Backed up collection.xml to {backup}")

    ET.indent(tree, space="  ")
    tree.write(collection_xml, encoding="utf-8", xml_declaration=True)
    log(f"Rewrote {collection_xml}")


def fix_alien_boxset_db(conn: sqlite3.Connection, dry_run: bool) -> None:
    rows = conn.execute(
        """
        SELECT Id, Name FROM BaseItems
        WHERE Path LIKE '%Alien Collection [boxset]%'
           OR Name = 'Alien Collection'
        """
    ).fetchall()
    for item_id, name in rows:
        log(f"Updating Alien box set item {item_id} metadata (was {name!r})")
        if dry_run:
            continue
        conn.execute(
            "UPDATE BaseItems SET Name=? WHERE Id=?",
            ("Alien Collection", item_id),
        )
        conn.execute(
            "DELETE FROM BaseItemProviders WHERE ItemId=? AND ProviderId='Tmdb' AND ProviderValue=?",
            (item_id, WRONG_ALIEN_TMDB),
        )
        exists = conn.execute(
            "SELECT 1 FROM BaseItemProviders WHERE ItemId=? AND ProviderId='Tmdb'",
            (item_id,),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO BaseItemProviders (ItemId, ProviderId, ProviderValue) VALUES (?, 'Tmdb', ?)",
                (item_id, ALIEN_TMDB_COLLECTION),
            )
        else:
            conn.execute(
                "UPDATE BaseItemProviders SET ProviderValue=? WHERE ItemId=? AND ProviderId='Tmdb'",
                (ALIEN_TMDB_COLLECTION, item_id),
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--collections-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    collections_root = Path(args.collections_root)
    alien_xml = collections_root / "Alien Collection [boxset]" / "collection.xml"

    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        log("Removing duplicate path rows (keep Episode/Movie over Video)...")
        dup_removed = remove_duplicate_paths(conn, args.dry_run)

        log("Removing duplicate/inferior movie encodes...")
        movie_removed = remove_movie_paths(conn, args.dry_run)

        log("Fixing Stephen King's The Stand parts mislabeled as Stand by Me...")
        stand_fixed = fix_stand_parts(conn, args.dry_run)

        log("Fixing Alien 3 display title...")
        alien3_fixed = fix_alien_three_title(conn, args.dry_run)

        log("Fixing Alien Collection metadata (TMDb 8091, 4-film anthology)...")
        write_alien_collection_xml(alien_xml, args.dry_run)
        fix_alien_boxset_db(conn, args.dry_run)

        if args.dry_run:
            conn.rollback()
            log("Dry run complete; no changes written.")
        else:
            conn.commit()
            log(
                "Applied changes: "
                f"duplicate_rows={dup_removed}, movies_removed={movie_removed}, "
                f"stand_fixed={stand_fixed}, alien3_fixed={alien3_fixed}"
            )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

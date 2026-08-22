"""Fill missing or junk album tags from parent directory when artist is known."""

from __future__ import annotations

import sys
from pathlib import Path

from beets import ui
from beets.plugins import BeetsPlugin
from beets.util import syspath

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from folder_tags import (  # noqa: E402
    album_from_folder,
    compile_junk,
    folder_names_for_path,
    in_unknown_album_folder,
    is_junk,
    merge_unknown_album_metadata,
)


def apply_folder_tags(item, libdir, junk_album_patterns, junk_artist_patterns, log) -> bool:
    changed = False
    path = Path(syspath(item.path))

    _, is_unknown = in_unknown_album_folder(path, Path(syspath(libdir)))
    if is_unknown:
        merged = merge_unknown_album_metadata(
            path, Path(syspath(libdir)), junk_album_patterns, junk_artist_patterns
        )
        field_map = {"tracknumber": "track"}
        for field, value in merged.items():
            item_field = field_map.get(field, field)
            if hasattr(item, item_field) and getattr(item, item_field) != value:
                setattr(item, item_field, value)
                changed = True
        if changed:
            log.info("metadata merged for Unknown Album path: {}", item.path)

    folder_artist, folder_album = folder_names_for_path(syspath(item.path), libdir)

    new_album = album_from_folder(
        item.album,
        folder_album,
        item.artist,
        item.albumartist,
        folder_artist,
        junk_album_patterns,
        junk_artist_patterns,
    )
    if new_album:
        item.album = new_album
        log.info("album from folder: {.album}", item)
        changed = True

    if folder_artist:
        if is_junk(item.albumartist, junk_artist_patterns):
            item.albumartist = folder_artist
            changed = True
        if is_junk(item.artist, junk_artist_patterns):
            item.artist = folder_artist
            changed = True

    return changed


class FromFolderPlugin(BeetsPlugin):
    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "auto": True,
                "junk_albums": [
                    r"^\s*$",
                    r"^\[cover\]$",
                    r"^\[unknown\]$",
                    r"^unknown album$",
                    r"^unknown$",
                ],
                "junk_artists": [
                    r"^\s*$",
                    r"^\[cover\]$",
                    r"^\[unknown\]$",
                    r"^unknown artist$",
                    r"^unknown$",
                ],
            }
        )
        self.junk_album_patterns = compile_junk(self.config["junk_albums"].as_str_seq())
        self.junk_artist_patterns = compile_junk(self.config["junk_artists"].as_str_seq())
        self.register_listener("import_task_start", self.import_task_start)

    def import_task_start(self, session, task):
        if not self.config["auto"]:
            return

        items = task.items if task.is_album else [task.item]
        for item in items:
            apply_folder_tags(
                item,
                session.lib.directory,
                self.junk_album_patterns,
                self.junk_artist_patterns,
                self._log,
            )

    def commands(self):
        cmd = ui.Subcommand(
            "fromfolder",
            help="set album from parent folder when artist is known",
        )
        cmd.parser.add_option(
            "-w",
            "--write",
            action="store_true",
            default=False,
            help="write updated tags to media files",
        )
        cmd.func = self.fromfolder_command
        return [cmd]

    def fromfolder_command(self, lib, opts, args):
        updated = 0
        for item in lib.items():
            if apply_folder_tags(
                item,
                lib.directory,
                self.junk_album_patterns,
                self.junk_artist_patterns,
                self._log,
            ):
                item.store()
                if opts.write:
                    item.write()
                updated += 1
        ui.print_(f"Updated {updated} item(s) from folder names.")

"""Tests for music ingestion pipeline helpers."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import pytest

INGEST_SRC = Path(__file__).resolve().parents[1] / "services" / "music-ingest" / "src"
sys.path.insert(0, str(INGEST_SRC))

from beets_runner import count_audio_files, find_import_candidates, folder_is_stable  # noqa: E402
from pipeline_config import PipelineConfig, is_ignored_path  # noqa: E402


def test_ignored_paths() -> None:
    incoming = Path(r"E:\Music\Incoming\Soulseek")
    assert is_ignored_path(incoming / "incomplete" / "file.part", incoming)
    assert not is_ignored_path(incoming / "artist" / "album", incoming)


def test_find_import_candidates_min_audio() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        incoming = Path(tmp)
        album = incoming / "Artist" / "Album"
        album.mkdir(parents=True)
        (album / "01-track.flac").write_bytes(b"fake")

        config = PipelineConfig(
            incoming_dir=incoming,
            library_dir=incoming / "library",
            quarantine_dir=incoming / "quarantine",
            state_dir=incoming / "state",
            beets_config=incoming / "config.yaml",
            stability_seconds=1,
            poll_interval_seconds=1,
            min_audio_files=1,
            log_dir=incoming / "logs",
            log_file="test.log",
        )

        candidates = find_import_candidates(incoming, config)
        assert album in candidates
        assert count_audio_files(album) == 1


def test_folder_stability_requires_quiet_period() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        album = Path(tmp)
        track = album / "01-track.mp3"
        track.write_bytes(b"fake")
        assert not folder_is_stable(album, stability_seconds=60)
        old = time.time() - 120
        track.touch()
        import os

        os.utime(track, (old, old))
        assert folder_is_stable(album, stability_seconds=60)

"""Pipeline configuration loaded from pipeline.env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _expand(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value.strip()))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


@dataclass(frozen=True)
class PipelineConfig:
    incoming_dir: Path
    library_dir: Path
    quarantine_dir: Path
    state_dir: Path
    beets_config: Path
    stability_seconds: int
    poll_interval_seconds: int
    min_audio_files: int
    log_dir: Path
    log_file: str

    @property
    def log_path(self) -> Path:
        return self.log_dir / self.log_file

    @property
    def processed_state_path(self) -> Path:
        return self.state_dir / "processed-paths.json"

    @property
    def pending_state_path(self) -> Path:
        return self.state_dir / "pending-imports.json"

    @property
    def incomplete_dir(self) -> Path:
        return self.incoming_dir / "incomplete"

    @classmethod
    def from_env(cls) -> PipelineConfig:
        return cls(
            incoming_dir=Path(_expand(os.environ.get("INCOMING_DIR", r"E:\Music\Incoming\Soulseek"))),
            library_dir=Path(_expand(os.environ.get("LIBRARY_DIR", r"E:\Music\Library"))),
            quarantine_dir=Path(_expand(os.environ.get("QUARANTINE_DIR", r"E:\Music\Quarantine"))),
            state_dir=Path(_expand(os.environ.get("STATE_DIR", r"E:\Music\State"))),
            beets_config=Path(_expand(os.environ.get("BEETS_CONFIG", r"%APPDATA%\beets\config.yaml"))),
            stability_seconds=_env_int("STABILITY_SECONDS", 120),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 30),
            min_audio_files=_env_int("MIN_AUDIO_FILES", 1),
            log_dir=Path(_expand(os.environ.get("LOG_DIR", r"C:\Users\adminnie\Projects\endurance-coach\logs"))),
            log_file=os.environ.get("LOG_FILE", "music-ingest.log"),
        )


AUDIO_EXTENSIONS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".alac"}
IGNORED_DIR_NAMES = {"incomplete", "downloading", "complete", "state", "library", "quarantine"}
TEMP_SUFFIXES = (".part", ".tmp", ".download", ".crdownload", ".partial")
IGNORED_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def is_ignored_path(path: Path, incoming_root: Path) -> bool:
    try:
        rel = path.relative_to(incoming_root)
    except ValueError:
        return True

    parts = rel.parts
    if not parts:
        return False
    if parts[0].lower() in IGNORED_DIR_NAMES:
        return True

    name = path.name.lower()
    if name in IGNORED_FILE_NAMES:
        return True
    if name.startswith("."):
        return True
    if any(name.endswith(suffix) for suffix in TEMP_SUFFIXES):
        return True
    return False

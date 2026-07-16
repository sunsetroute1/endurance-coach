"""Run beets import for stable incoming folders."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from pipeline_config import AUDIO_EXTENSIONS, PipelineConfig, is_audio_file, is_ignored_path

logger = logging.getLogger("music_ingest.beets")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_json(path: Path, default: dict | list) -> dict | list:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt state file %s; resetting", path)
        return default


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def count_audio_files(folder: Path) -> int:
    total = 0
    for path in folder.rglob("*"):
        if path.is_file() and is_audio_file(path):
            total += 1
    return total


def find_import_candidates(root: Path, config: PipelineConfig) -> list[Path]:
    candidates: list[Path] = []
    if not root.exists():
        return candidates

    for path in sorted(root.rglob("*")):
        if not path.is_dir():
            continue
        if is_ignored_path(path, config.incoming_dir):
            continue
        if count_audio_files(path) < config.min_audio_files:
            continue
        if any(child.is_dir() and count_audio_files(child) >= config.min_audio_files for child in path.iterdir()):
            continue
        candidates.append(path)

    deduped: dict[str, Path] = {}
    for candidate in candidates:
        deduped[str(candidate.resolve()).lower()] = candidate
    return sorted(deduped.values(), key=lambda p: str(p).lower())


def folder_is_stable(folder: Path, stability_seconds: int) -> bool:
    if not folder.exists():
        return False

    newest_mtime = 0.0
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.suffix.lower() not in AUDIO_EXTENSIONS:
            continue
        newest_mtime = max(newest_mtime, path.stat().st_mtime)

    if newest_mtime == 0.0:
        return False

    age = datetime.now().timestamp() - newest_mtime
    return age >= stability_seconds


def resolve_beet_executable(venv_python: Path | None = None) -> list[str]:
    if venv_python and venv_python.exists():
        beet = venv_python.parent / "beet.exe"
        if beet.exists():
            return [str(beet)]
        return [str(venv_python), "-m", "beets.ui.cli"]

    for candidate in ("beet", "beet.exe"):
        found = shutil.which(candidate)
        if found:
            return [found]

    return [sys.executable, "-m", "beets.ui.cli"]


def run_beet_import(folder: Path, config: PipelineConfig, venv_python: Path | None = None) -> int:
    env = os.environ.copy()
    env["BEETSDIR"] = str(config.beets_config.parent)
    beet_cmd = resolve_beet_executable(venv_python)
    command = [
        *beet_cmd,
        "-c",
        str(config.beets_config),
        "import",
        "-q",
        "-s",
        "-m",
        str(folder),
    ]
    logger.info("Running beets import for %s", folder)
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    if result.stdout.strip():
        logger.info("beet stdout: %s", result.stdout.strip()[-4000:])
    if result.stderr.strip():
        logger.warning("beet stderr: %s", result.stderr.strip()[-4000:])
    return result.returncode


def mark_processed(state_path: Path, folder: Path, return_code: int) -> None:
    state = load_json(state_path, default={})
    if not isinstance(state, dict):
        state = {}
    state[str(folder.resolve()).lower()] = {
        "path": str(folder),
        "return_code": return_code,
        "processed_at": _utc_now(),
    }
    save_json(state_path, state)


def already_processed(state_path: Path, folder: Path) -> bool:
    state = load_json(state_path, default={})
    if not isinstance(state, dict):
        return False
    entry = state.get(str(folder.resolve()).lower())
    if not entry:
        return False
    return int(entry.get("return_code", 1)) == 0


def import_stable_folder(folder: Path, config: PipelineConfig, venv_python: Path | None = None) -> bool:
    if already_processed(config.processed_state_path, folder):
        logger.debug("Skipping already processed folder %s", folder)
        return True

    if not folder_is_stable(folder, config.stability_seconds):
        logger.debug("Folder not stable yet: %s", folder)
        return False

    return_code = run_beet_import(folder, config, venv_python=venv_python)
    mark_processed(config.processed_state_path, folder, return_code)

    if return_code == 0:
        logger.info("Imported %s successfully", folder)
        return True

    logger.error("beets import failed (%s) for %s", return_code, folder)
    return False


def scan_and_import(config: PipelineConfig, venv_python: Path | None = None) -> int:
    imported = 0
    for folder in find_import_candidates(config.incoming_dir, config):
        if import_stable_folder(folder, config, venv_python=venv_python):
            imported += 1
    return imported

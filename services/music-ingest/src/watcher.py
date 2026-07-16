"""Watch Soulseek incoming folder and trigger beets imports."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from beets_runner import import_stable_folder, scan_and_import
from pipeline_config import PipelineConfig, is_ignored_path


def setup_logging(config: PipelineConfig) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.FileHandler(config.log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


class DebouncedImportHandler(FileSystemEventHandler):
    def __init__(self, config: PipelineConfig, venv_python: Path | None) -> None:
        super().__init__()
        self.config = config
        self.venv_python = venv_python
        self._lock = threading.Lock()
        self._pending: dict[str, float] = {}
        self._logger = logging.getLogger("music_ingest.watcher")

    def _schedule(self, path: Path) -> None:
        if path.is_file():
            path = path.parent
        if is_ignored_path(path, self.config.incoming_dir):
            return
        key = str(path.resolve()).lower()
        with self._lock:
            self._pending[key] = time.time()
            self._logger.debug("Scheduled import check for %s", path)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            self._schedule(Path(event.src_path))
        else:
            self._schedule(Path(event.src_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            self._schedule(Path(event.src_path))
        else:
            self._schedule(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._schedule(Path(event.dest_path))

    def process_pending(self) -> None:
        now = time.time()
        ready: list[Path] = []
        with self._lock:
            for key, scheduled_at in list(self._pending.items()):
                if now - scheduled_at < self.config.stability_seconds:
                    continue
                ready.append(Path(key))
                del self._pending[key]

        for folder in ready:
            import_stable_folder(folder, self.config, venv_python=self.venv_python)


def run_watcher(config: PipelineConfig, venv_python: Path | None) -> int:
    logger = logging.getLogger("music_ingest.watcher")
    config.incoming_dir.mkdir(parents=True, exist_ok=True)
    config.incomplete_dir.mkdir(parents=True, exist_ok=True)

    handler = DebouncedImportHandler(config, venv_python)
    observer = Observer()
    observer.schedule(handler, str(config.incoming_dir), recursive=True)
    observer.start()
    logger.info("Watching %s (stability=%ss)", config.incoming_dir, config.stability_seconds)

    try:
        while True:
            handler.process_pending()
            time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Stopping watcher")
    finally:
        observer.stop()
        observer.join()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Music ingestion watcher")
    parser.add_argument("--env-file", default=None, help="Optional pipeline.env path")
    parser.add_argument("--scan-once", action="store_true", help="Run one beets scan and exit")
    parser.add_argument("--venv-python", default=None, help="Python executable from music-ingest venv")
    args = parser.parse_args()

    ingest_root = Path(__file__).resolve().parents[1]
    env_file = Path(args.env_file) if args.env_file else ingest_root / "config" / "pipeline.env"
    load_env_file(env_file)

    config = PipelineConfig.from_env()
    setup_logging(config)
    venv_python = Path(args.venv_python) if args.venv_python else None

    if args.scan_once:
        imported = scan_and_import(config, venv_python=venv_python)
        logging.getLogger("music_ingest").info("Scan complete; processed %s candidate folder(s)", imported)
        return 0

    return run_watcher(config, venv_python)


if __name__ == "__main__":
    raise SystemExit(main())

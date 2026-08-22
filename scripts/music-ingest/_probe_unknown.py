from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parents[2] / "services" / "music-ingest" / "src"
sys.path.insert(0, str(_SRC))
from folder_tags import read_easy_tags

root = Path(r"E:\Music")
underscore = root / "_" / "Singles"
if underscore.is_dir():
    mp3s = list(underscore.glob("*.mp3"))
    print(f"_/Singles: {len(mp3s)} mp3s")
    for f in mp3s[:5]:
        _, t = read_easy_tags(f)
        print(f"  {f.name[:70]}")
        print(f"    artist={t.get('artist')!r} album={t.get('album')!r} title={t.get('title')!r}")

k = root / "Krs-One"
if k.is_dir():
    mp3s = list(k.rglob("*.mp3"))
    print(f"Krs-One: {len(mp3s)} mp3s")
    bad = 0
    for f in mp3s[:5]:
        _, t = read_easy_tags(f)
        a = (t.get("artist") or "").strip()
        if not a or a.lower() in {"unknown artist", "[unknown]"}:
            bad += 1
        print(f"  {f.relative_to(k)} -> artist={t.get('artist')!r}")
    print(f"  (sample bad tags in first 5: {bad})")

q = root / "Quarantine"
if q.is_dir():
    mp3s = list(q.rglob("*.mp3"))
    print(f"Quarantine: {len(mp3s)} mp3s")

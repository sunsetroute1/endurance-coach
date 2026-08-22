import sqlite3
from pathlib import Path

db = Path(r"E:\Music\State\beets-library.blb")
print("db exists:", db.exists())
for p in sorted(db.parent.glob("beets-library.blb*")):
    print(p.name, p.stat().st_size)

for timeout in (1, 5, 30):
    try:
        conn = sqlite3.connect(str(db), timeout=timeout)
        conn.execute("BEGIN IMMEDIATE")
        count = conn.execute("SELECT count(*) FROM items").fetchone()[0]
        print(f"lock ok timeout={timeout}, items={count}")
        conn.rollback()
        conn.close()
        break
    except Exception as exc:
        print(f"timeout={timeout}: {exc}")

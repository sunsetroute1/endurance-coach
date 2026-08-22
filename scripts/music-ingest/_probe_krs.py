from pathlib import Path
import sys
sys.path.insert(0, r"C:\Users\adminnie\Projects\endurance-coach\services\music-ingest\src")
from folder_tags import read_easy_tags, folder_names_for_path, fix_file_tags, compile_junk, album_from_folder, known_artist

libdir = Path(r"E:\Music")
path = libdir / "Krs-One" / "Adventures In Emceein" / "01 Intro (By Rakim).mp3"
if path.exists():
    _, t = read_easy_tags(path)
    fa, fal = folder_names_for_path(path, libdir)
    junk_a = compile_junk()
    junk_b = compile_junk()
    print("tags:", t)
    print("folder:", fa, fal)
    print("known_artist:", known_artist(t.get("artist"), t.get("albumartist"), fa, junk_a))
    print("album_from_folder:", album_from_folder(t.get("album"), fal, t.get("artist"), t.get("albumartist"), fa, junk_b, junk_a))

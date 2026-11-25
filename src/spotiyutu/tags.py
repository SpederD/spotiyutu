import re
from pathlib import Path

import requests
from mutagen import MutagenError
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError


def safe(s: str) -> str:
    """Sanitize string for safe cross-platform file and directory names, preserving unicode."""
    # Remove characters forbidden on Windows / Unix: < > : " / \ | ? * and control chars
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    # Collapse multiple spaces or underscores
    clean = re.sub(r"\s+", " ", clean).strip(". ")
    return clean[:120] if clean else "unnamed"


def apply_tags(mp3: Path, meta: dict):
    try:
        tags = ID3(str(mp3))
    except (ID3NoHeaderError, MutagenError):
        tags = ID3()

    if meta.get("title"):
        tags["TIT2"] = TIT2(encoding=3, text=str(meta["title"]))
    if meta.get("artist"):
        tags["TPE1"] = TPE1(encoding=3, text=str(meta["artist"]))
    if meta.get("album"):
        tags["TALB"] = TALB(encoding=3, text=str(meta["album"]))

    track_num = meta.get("track_number")
    total_tracks = meta.get("total_tracks")
    if track_num is not None:
        trck_val = f"{track_num}/{total_tracks}" if total_tracks else str(track_num)
        tags["TRCK"] = TRCK(encoding=3, text=trck_val)

    year = meta.get("year") or meta.get("release_date")
    if year:
        tags["TDRC"] = TDRC(encoding=3, text=str(year)[:4])

    cover = meta.get("cover")
    if cover:
        try:
            r = requests.get(cover, timeout=15)
            if r.ok:
                mime = (
                    "image/jpeg" if cover.endswith((".jpg", ".jpeg")) else "image/png"
                )
                tags["APIC"] = APIC(
                    encoding=3, mime=mime, type=3, desc="cover", data=r.content
                )
        except requests.RequestException:
            pass

    tags.save(str(mp3))

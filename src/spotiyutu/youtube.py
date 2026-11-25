import re
import subprocess
from pathlib import Path

import yt_dlp

from . import config


def _opts(out_tmpl: str, noplaylist: bool = True, bitrate: str = "320") -> dict:
    opts = {
        "format": "bestaudio[abr>=128]/bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": out_tmpl,
        "noplaylist": noplaylist,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "nocheckcertificate": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(bitrate),
            }
        ],
    }
    ff_dir = config.get_ffmpeg_dir()
    if ff_dir:
        opts["ffmpeg_location"] = ff_dir
    return opts


def find_audio_candidates(
    query: str, expected_duration: float | None = None
) -> list[str]:
    """Search YouTube and rank results to pick clean studio audio releases over music videos or DJ mixes."""
    if query.startswith("http"):
        return [query]

    q_lower = query.lower()
    if " - " in q_lower:
        artist_part, title_part = q_lower.split(" - ", 1)
    else:
        artist_part, title_part = "", q_lower

    clean_title = re.sub(r"\(.*?\)|\[.*?\]", "", title_part).strip()
    title_words = [w for w in re.findall(r"\w+", clean_title) if len(w) >= 3]
    if not title_words:
        title_words = [w for w in re.findall(r"\w+", title_part) if len(w) >= 2]
    artist_words = [w for w in re.findall(r"\w+", artist_part) if len(w) >= 3]

    def score_entry(entry: dict, rank_idx: int) -> float:
        if not entry:
            return -9999.0

        # Reject upcoming premieres and live streams
        live_status = entry.get("live_status")
        if live_status in ("is_upcoming", "is_live", "post_live"):
            return -9999.0

        title = (entry.get("title") or "").lower()
        channel = (entry.get("channel") or entry.get("uploader") or "").lower()
        combined = f"{title} {channel}"
        dur = entry.get("duration") or 0

        # Hard duration guard: never download 1-2 hour DJ mixes or wrong-length tracks
        if expected_duration:
            if dur <= 0:
                return -9999.0
            diff = abs(dur - expected_duration)
            if diff > max(90.0, expected_duration * 0.5):
                return -9999.0
        elif dur > 900 and "mix" not in q_lower and "set" not in q_lower:
            return -9999.0

        score = max(0.0, 15.0 - rank_idx * 2.0)

        # Title relevance check
        if title_words:
            matched_title = sum(1 for w in title_words if w in combined)
            if matched_title == 0:
                return -9999.0
            score += (matched_title / len(title_words)) * 45.0

        # Artist relevance check
        if artist_words:
            matched_artist = sum(1 for w in artist_words if w in combined)
            if matched_artist > 0:
                score += 25.0

        # 1. Official Topic channel: label uncompressed studio master
        if "- topic" in channel or channel.endswith("topic"):
            score += 55.0

        # 2. Official audio / visualiser bonus
        if "official audio" in title:
            score += 35.0
        elif "audio" in title or "visualiser" in title or "visualizer" in title:
            score += 15.0

        # 3. Penalize music videos (skits, sound effects, compressed TV/mobile mix)
        if any(
            w in title
            for w in (
                "official music video",
                "music video",
                "official video",
                "video clip",
            )
        ):
            score -= 35.0
        elif "video" in title:
            score -= 15.0

        # 4. Strictly penalize unwanted variants unless query explicitly asks for them
        penalties = [
            ("live", -85.0),
            ("concert", -85.0),
            ("cover", -85.0),
            ("karaoke", -95.0),
            ("instrumental", -70.0),
            ("slowed", -95.0),
            ("reverb", -95.0),
            ("remix", -45.0),
            ("vip", -35.0),
            ("acoustic", -50.0),
            ("bass boosted", -90.0),
            ("8d", -90.0),
            ("podcast", -150.0),
            ("radio", -100.0),
        ]
        for word, pen in penalties:
            if word in title and word not in q_lower:
                score += pen

        # 5. Duration match precision with Spotify metadata
        if expected_duration and dur > 0:
            diff = abs(dur - expected_duration)
            if diff <= 3:
                score += 45.0
            elif diff <= 7:
                score += 25.0
            elif diff <= 15:
                score += 10.0
            elif diff <= 30:
                score -= 20.0
            else:
                score -= 50.0

        return score

    search_queries = [
        f"ytsearch6:{query}",
        f"ytsearch5:{query} topic",
        f"ytsearch5:{query} Audio",
    ]
    scored: list[tuple[float, str]] = []
    seen_ids: set[str] = set()

    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
    ) as ydl:
        for sq in search_queries:
            try:
                res = ydl.extract_info(sq, download=False) or {}
                entries = [e for e in (res.get("entries") or []) if e]
            except Exception:
                entries = []

            for idx, e in enumerate(entries):
                vid = e.get("id")
                if not vid or vid in seen_ids:
                    continue
                seen_ids.add(vid)
                s = score_entry(e, idx)
                if s > -1000:
                    url = f"https://www.youtube.com/watch?v={vid}"
                    scored.append((s, url))

            if any(item[0] >= 70 for item in scored):
                break

    if not scored:
        return [f"ytsearch1:{query}"]

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:3]]


def find_best_audio_match(query: str, expected_duration: float | None = None) -> str:
    """Return the single highest-scoring audio match URL for a search query."""
    candidates = find_audio_candidates(query, expected_duration=expected_duration)
    return candidates[0] if candidates else f"ytsearch1:{query}"


def download(
    query_or_url: str,
    dest: Path,
    filename: str,
    bitrate: str = "320",
    expected_duration: float | None = None,
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(dest / f"{filename}.%(ext)s")

    if query_or_url.startswith("http"):
        targets = [query_or_url]
    else:
        targets = find_audio_candidates(
            query_or_url, expected_duration=expected_duration
        )

    last_err = None
    for target in targets:
        try:
            with yt_dlp.YoutubeDL(
                _opts(out_tmpl, noplaylist=True, bitrate=bitrate)
            ) as ydl:
                ydl.extract_info(target, download=True)
            last_err = None
            break
        except Exception as e:
            last_err = e
            # Clean up any partial files before retrying next candidate
            for part in dest.glob(f"{filename}.*"):
                if part.suffix.lower() in (".part", ".ytdl", ".webm", ".m4a"):
                    try:
                        part.unlink()
                    except OSError:
                        pass
            continue

    if last_err is not None and not (dest / f"{filename}.mp3").exists():
        raise last_err

    mp3_file = dest / f"{filename}.mp3"
    if mp3_file.exists():
        return mp3_file

    # Safety check: if for any reason audio was kept in .webm/.m4a, convert it to mp3
    ff_exe = config.get_ffmpeg_exe()
    for ext in (".webm", ".m4a", ".opus", ".ogg", ".aac", ".flac"):
        cand = dest / f"{filename}{ext}"
        if cand.exists():
            if ff_exe:
                subprocess.run(
                    [
                        ff_exe,
                        "-y",
                        "-i",
                        str(cand),
                        "-vn",
                        "-ab",
                        f"{bitrate}k",
                        str(mp3_file),
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                if mp3_file.exists():
                    try:
                        cand.unlink()
                    except Exception:
                        pass
                    return mp3_file
            return cand
    return mp3_file


def playlist_entries(url: str, limit: int | None = None) -> tuple[str, list[dict]]:
    with yt_dlp.YoutubeDL(
        {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
        }
    ) as ydl:
        info = ydl.extract_info(url, download=False)
    title = info.get("title", "yt-playlist")
    out = []
    for e in (
        (info.get("entries") or [])[:limit] if limit else (info.get("entries") or [])
    ):
        if not e:
            continue
        vid = e.get("id")
        out.append(
            {
                "title": e.get("title", vid),
                "url": f"https://www.youtube.com/watch?v={vid}",
            }
        )
    return title, out

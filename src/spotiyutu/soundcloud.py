import yt_dlp


def is_soundcloud(url: str) -> bool:
    """Check if the given URL belongs to SoundCloud."""
    clean = url.lower().strip()
    return "soundcloud.com" in clean or "on.soundcloud.com" in clean


def get_info(url: str, flat: bool = True) -> dict:
    """Extract metadata for a SoundCloud URL using yt-dlp."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": flat,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


def track_meta(url: str) -> dict:
    """Get metadata for a single SoundCloud track."""
    info = get_info(url, flat=False)
    title = info.get("title") or "SoundCloud Track"
    artist = (
        info.get("uploader")
        or info.get("creator")
        or info.get("artist")
        or "SoundCloud Artist"
    )
    cover = info.get("thumbnail")
    year = (
        str(info.get("release_year") or (info.get("upload_date") or "")[:4] or "")
        or None
    )

    return {
        "title": title,
        "artist": artist,
        "album": "",
        "cover": cover,
        "year": year,
        "search": f"{artist} - {title}",
        "track_number": 1,
        "total_tracks": 1,
    }


def playlist_entries(url: str, limit: int | None = None) -> tuple[str, list[dict]]:
    """Get entries for a SoundCloud set/playlist."""
    info = get_info(url, flat=True)
    title = info.get("title") or "soundcloud-set"
    raw_entries = info.get("entries") or []
    selected = raw_entries[:limit] if limit else raw_entries

    out = []
    for idx, e in enumerate(selected, 1):
        if not e:
            continue
        t_url = e.get("url")
        if not t_url or not t_url.startswith("http"):
            t_url = e.get("webpage_url") or url

        t_title = e.get("title") or f"Track {idx}"
        t_artist = (
            e.get("uploader")
            or e.get("creator")
            or info.get("uploader")
            or "SoundCloud Artist"
        )
        t_cover = e.get("thumbnail") or info.get("thumbnail")

        out.append(
            {
                "title": t_title,
                "artist": t_artist,
                "album": title,
                "url": t_url,
                "cover": t_cover,
                "track_number": idx,
                "total_tracks": len(selected),
            }
        )

    return title, out

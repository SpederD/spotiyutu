import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import config, soundcloud, spotify, tags, youtube


def _one_spotify(
    meta: dict,
    out: Path,
    number: bool = False,
    bitrate: str = "320",
    on_track_status=None,
) -> Path:
    pad = len(str(meta.get("total_tracks") or 99))
    if number and meta.get("track_number") is not None:
        prefix = f"{meta['track_number']:0{max(2, pad)}d} - "
        base_name = f"{prefix}{meta['artist']} - {meta['title']}"
    else:
        base_name = f"{meta['artist']} - {meta['title']}"

    fname = tags.safe(base_name)
    mp3 = out / f"{fname}.mp3"

    if mp3.exists() and 10000 < mp3.stat().st_size < 40000000:
        if on_track_status:
            on_track_status("skipped", meta, mp3)
        return mp3

    if on_track_status:
        on_track_status("downloading", meta, None)

    mp3 = youtube.download(
        meta["search"],
        out,
        fname,
        bitrate=bitrate,
        expected_duration=meta.get("duration_s"),
    )

    if on_track_status:
        on_track_status("tagging", meta, mp3)

    spotify.enrich_track_meta(meta)
    tags.apply_tags(mp3, meta)

    if on_track_status:
        on_track_status("done", meta, mp3)

    return mp3


def _write_m3u(dest: Path, playlist_name: str, files: list[Path]):
    """Generate standard M3U playlist file."""
    m3u_path = dest / f"{tags.safe(playlist_name)}.m3u"
    try:
        with open(m3u_path, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n")
            f.writelines(f"{p.name}\n" for p in files)
    except OSError:
        pass


def download_spotify(
    url: str,
    out: Path | None = None,
    limit: int | None = None,
    threads: int = 3,
    number: bool = True,
    m3u: bool = True,
    bitrate: str = "320",
    on_progress=None,
    on_track_status=None,
) -> tuple[str, list[Path]]:
    out = out or config.out_dir()
    kind, _ = spotify.parse_url(url)

    if kind == "track":
        meta = spotify.track_meta(url)
        single_path = _one_spotify(
            meta, out, number=False, bitrate=bitrate, on_track_status=on_track_status
        )
        if on_progress:
            on_progress(1, 1, meta)
        return meta["title"], [single_path]

    name, metas = (
        spotify.playlist_metas(url, limit)
        if kind == "playlist"
        else spotify.album_metas(url)
    )
    dest = out / tags.safe(name)
    dest.mkdir(parents=True, exist_ok=True)

    if on_progress:
        on_progress(0, len(metas), {"title": name, "playlist_name": name})

    done: list[Path | None] = [None] * len(metas)
    completed_count = 0
    lock = threading.Lock()

    def process_item(idx: int, m: dict):
        nonlocal completed_count
        try:
            res = _one_spotify(
                m, dest, number=number, bitrate=bitrate, on_track_status=on_track_status
            )
            with lock:
                done[idx] = res
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, len(metas), m)
            return res
        except Exception as e:
            if on_track_status:
                on_track_status("error", m, None, error=str(e))
            with lock:
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, len(metas), m)
            return None

    worker_count = max(1, min(threads, len(metas))) if threads > 1 else 1
    if worker_count > 1:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(process_item, i, m) for i, m in enumerate(metas)]
            for f in as_completed(futures):
                pass
    else:
        for i, m in enumerate(metas):
            process_item(i, m)

    valid_files = [p for p in done if p is not None]
    if m3u and valid_files:
        _write_m3u(dest, name, valid_files)

    return name, valid_files


def download_youtube(
    url: str,
    out: Path | None = None,
    limit: int | None = None,
    threads: int = 3,
    number: bool = True,
    m3u: bool = True,
    bitrate: str = "320",
    on_progress=None,
    on_track_status=None,
) -> tuple[str, list[Path]]:
    out = out or config.out_dir()
    if "list=" in url:
        title, entries = youtube.playlist_entries(url, limit)
        dest = out / tags.safe(title)
        dest.mkdir(parents=True, exist_ok=True)
        total = len(entries)

        done: list[Path | None] = [None] * total
        completed_count = 0
        lock = threading.Lock()
        pad = len(str(total or 99))

        def process_yt_entry(idx: int, e: dict):
            nonlocal completed_count
            try:
                t_num = idx + 1
                prefix = f"{t_num:0{max(2, pad)}d} - " if number else ""
                fname = tags.safe(f"{prefix}{e['title']}")
                mp3 = dest / f"{fname}.mp3"
                meta = {
                    "title": e["title"],
                    "artist": "",
                    "album": title,
                    "track_number": t_num,
                    "total_tracks": total,
                }
                if not (mp3.exists() and mp3.stat().st_size > 10000):
                    if on_track_status:
                        on_track_status("downloading", meta, None)
                    mp3 = youtube.download(e["url"], dest, fname, bitrate=bitrate)
                    tags.apply_tags(mp3, meta)
                if on_track_status:
                    on_track_status("done", meta, mp3)
                with lock:
                    done[idx] = mp3
                    completed_count += 1
                    if on_progress:
                        on_progress(completed_count, total, meta)
                return mp3
            except Exception as ex:
                if on_track_status:
                    on_track_status("error", {"title": e["title"]}, None, error=str(ex))
                with lock:
                    completed_count += 1
                    if on_progress:
                        on_progress(completed_count, total, {"title": e["title"]})
                return None

        worker_count = max(1, min(threads, total)) if threads > 1 else 1
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(process_yt_entry, i, e)
                    for i, e in enumerate(entries)
                ]
                for f in as_completed(futures):
                    pass
        else:
            for i, e in enumerate(entries):
                process_yt_entry(i, e)

        valid_files = [p for p in done if p is not None]
        if m3u and valid_files:
            _write_m3u(dest, title, valid_files)
        return title, valid_files

    track_path = download_youtube_track(url, out, bitrate=bitrate)
    if on_progress:
        on_progress(1, 1, {"title": track_path.stem})
    return track_path.stem, [track_path]


def download_youtube_track(
    url: str, out: Path | None = None, bitrate: str = "320"
) -> Path:
    out = out or config.out_dir()
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        title = info.get("title", "yt-audio")
    meta = {
        "title": title,
        "artist": info.get("uploader", ""),
        "album": "",
        "cover": info.get("thumbnail"),
    }
    fname = tags.safe(title)
    mp3 = youtube.download(url, out, fname, bitrate=bitrate)
    tags.apply_tags(mp3, meta)
    return mp3


def download_search(query: str, out: Path | None = None, bitrate: str = "320") -> Path:
    out = out or config.out_dir()
    fname = tags.safe(query)
    mp3 = youtube.download(query, out, fname, bitrate=bitrate)
    tags.apply_tags(mp3, {"title": query, "artist": "", "album": ""})
    return mp3


def download_soundcloud(
    url: str,
    out: Path | None = None,
    limit: int | None = None,
    threads: int = 3,
    number: bool = False,
    m3u: bool = False,
    bitrate: str = "320",
    on_progress=None,
    on_track_status=None,
) -> tuple[str, list[Path]]:
    out = out or config.out_dir()
    clean = url.lower()

    if "/sets/" in clean:
        title, entries = soundcloud.playlist_entries(url, limit=limit)
        dest = out / tags.safe(title)
        dest.mkdir(parents=True, exist_ok=True)
        total = len(entries)
        done: list[Path | None] = [None] * total
        completed_count = 0
        lock = threading.Lock()
        pad = len(str(total or 99))

        def process_sc_entry(idx: int, e: dict):
            nonlocal completed_count
            try:
                t_num = idx + 1
                prefix = f"{t_num:0{max(2, pad)}d} - " if number else ""
                artist_part = f"{e['artist']} - " if e.get("artist") else ""
                fname = tags.safe(f"{prefix}{artist_part}{e['title']}")
                mp3 = dest / f"{fname}.mp3"
                meta = {
                    "title": e["title"],
                    "artist": e.get("artist", ""),
                    "album": title,
                    "cover": e.get("cover"),
                    "track_number": t_num,
                    "total_tracks": total,
                }
                if not (mp3.exists() and mp3.stat().st_size > 10000):
                    if on_track_status:
                        on_track_status("downloading", meta, None)
                    mp3 = youtube.download(e["url"], dest, fname, bitrate=bitrate)
                    tags.apply_tags(mp3, meta)
                if on_track_status:
                    on_track_status("done", meta, mp3)
                with lock:
                    done[idx] = mp3
                    completed_count += 1
                    if on_progress:
                        on_progress(completed_count, total, meta)
                return mp3
            except Exception as ex:
                if on_track_status:
                    on_track_status("error", {"title": e["title"]}, None, error=str(ex))
                with lock:
                    completed_count += 1
                    if on_progress:
                        on_progress(completed_count, total, {"title": e["title"]})
                return None

        worker_count = max(1, min(threads, total)) if threads > 1 else 1
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [
                    executor.submit(process_sc_entry, i, e)
                    for i, e in enumerate(entries)
                ]
                for f in as_completed(futures):
                    pass
        else:
            for i, e in enumerate(entries):
                process_sc_entry(i, e)

        valid_files = [p for p in done if p is not None]
        if m3u and valid_files:
            _write_m3u(dest, title, valid_files)
        return title, valid_files

    # Single track
    meta = soundcloud.track_meta(url)
    artist_part = f"{meta['artist']} - " if meta.get("artist") else ""
    prefix = f"{meta['track_number']:02d} - " if number else ""
    fname = tags.safe(f"{prefix}{artist_part}{meta['title']}")
    mp3 = out / f"{fname}.mp3"

    if mp3.exists() and mp3.stat().st_size > 10000:
        if on_track_status:
            on_track_status("skipped", meta, mp3)
        if on_progress:
            on_progress(1, 1, meta)
        return meta["title"], [mp3]

    if on_track_status:
        on_track_status("downloading", meta, None)

    mp3 = youtube.download(url, out, fname, bitrate=bitrate)

    if on_track_status:
        on_track_status("tagging", meta, mp3)

    tags.apply_tags(mp3, meta)

    if on_track_status:
        on_track_status("done", meta, mp3)

    if on_progress:
        on_progress(1, 1, meta)

    return meta["title"], [mp3]

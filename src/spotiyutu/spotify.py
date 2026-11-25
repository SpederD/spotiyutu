import json
import logging
import re
from pathlib import Path

import requests
import spotipy
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth

from . import config

# Silence noisy spotipy HTTP error logs when falling back to embed scraper
logging.getLogger("spotipy").setLevel(logging.CRITICAL)
logging.getLogger("spotipy.client").setLevel(logging.CRITICAL)

URL_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-zA-Z-]+/)?(track|album|playlist)/|spotify:(track|album|playlist):)([A-Za-z0-9]+)"
)

EMBED_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )
}


def get_client() -> spotipy.Spotify:
    cid, secret = config.spotify_creds()
    if not cid or not secret:
        raise RuntimeError("Missing SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET in .env")
    auth = SpotifyClientCredentials(client_id=cid, client_secret=secret)
    return spotipy.Spotify(
        auth_manager=auth, retries=0, status_forcelist=(), requests_timeout=8
    )


def get_user_client(open_browser: bool = True) -> spotipy.Spotify:
    cid, secret = config.spotify_creds()
    if not cid or not secret:
        raise RuntimeError("Missing SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET in .env")
    auth = SpotifyOAuth(
        client_id=cid,
        client_secret=secret,
        redirect_uri=config.spotify_redirect(),
        scope="playlist-read-private playlist-read-collaborative user-library-read",
        cache_path=config.spotify_cache(),
        open_browser=open_browser,
    )
    return spotipy.Spotify(
        auth_manager=auth, retries=0, status_forcelist=(), requests_timeout=8
    )


def _clear_broken_user_cache():
    cache_p = Path(config.spotify_cache())
    if cache_p.exists():
        try:
            cache_p.unlink()
        except OSError:
            pass


def parse_url(url: str) -> tuple[str, str]:
    if "collection/tracks" in url or url.strip() == "liked":
        return "playlist", "liked"
    m = URL_RE.search(url)
    if not m:
        raise ValueError(
            f"Not a recognized Spotify track, album, or playlist URL: {url}"
        )
    kind = m.group(1) or m.group(2)
    sid = m.group(3)
    return kind, sid


def _from_track_obj(t: dict, index: int = 1, total: int = 1) -> dict:
    artists = [a["name"] for a in t.get("artists", []) if a and a.get("name")]
    artist_str = ", ".join(artists) if artists else "Unknown Artist"
    album = t.get("album", {}) or {}
    images = album.get("images", []) if isinstance(album, dict) else []
    cover = images[0]["url"] if images else None
    year = (album.get("release_date") or "")[:4] if isinstance(album, dict) else None
    name = t.get("name", "Unknown Title")
    dur_ms = t.get("duration_ms") or t.get("duration") or 0
    duration_s = round(dur_ms / 1000, 1) if dur_ms else None
    return {
        "title": name,
        "artists": artists,
        "artist": artist_str,
        "album": album.get("name", "") if isinstance(album, dict) else "",
        "cover": cover,
        "year": year,
        "search": f"{artist_str} - {name}",
        "duration_s": duration_s,
        "track_number": index,
        "total_tracks": total,
        "track_id": t.get("id"),
    }


def _fetch_embed_entity(kind: str, sid: str) -> dict:
    embed_url = f"https://open.spotify.com/embed/{kind}/{sid}"
    r = requests.get(embed_url, headers=EMBED_HEADERS, timeout=15)
    if not r.ok:
        raise RuntimeError(
            f"Failed to fetch Spotify embed page (HTTP {r.status_code}) for {kind} {sid}"
        )
    m = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', r.text)
    if not m:
        raise RuntimeError(
            f"Could not extract metadata from Spotify embed for {kind} {sid}"
        )
    data = json.loads(m.group(1))
    return (
        data.get("props", {})
        .get("pageProps", {})
        .get("state", {})
        .get("data", {})
        .get("entity", {})
    )


def _extract_embed_cover(entity: dict) -> str | None:
    sources = (entity.get("coverArt") or {}).get("sources", [])
    if not sources:
        sources = (entity.get("visualIdentity") or {}).get("image", [])
    if not sources:
        return None
    # Pick highest resolution source (usually 640x640)
    best = max(sources, key=lambda s: s.get("maxWidth") or s.get("width") or 0)
    url = best.get("url")
    if url:
        return url.replace("00001e02", "0000b273").replace(
            "image-cdn-fa.spotifycdn.com", "i.scdn.co"
        )
    return None


def enrich_track_meta(m: dict) -> dict:
    """Lazily resolve individual track HD cover art via Spotify oEmbed (no API key or rate limit)."""
    tid = m.get("track_id")
    if not tid or not m.get("needs_cover_enrich"):
        return m
    try:
        r = requests.get(
            f"https://open.spotify.com/oembed?url=https://open.spotify.com/track/{tid}",
            timeout=6,
        )
        if r.ok:
            data = r.json()
            thumb = data.get("thumbnail_url")
            if thumb:
                m["cover"] = thumb.replace("00001e02", "0000b273").replace(
                    "image-cdn-fa.spotifycdn.com", "i.scdn.co"
                )
    except Exception:
        pass
    m["needs_cover_enrich"] = False
    return m


def _track_meta_from_embed(sid: str) -> dict:
    entity = _fetch_embed_entity("track", sid)
    title = entity.get("title") or entity.get("name") or "Unknown Title"
    raw_artists = entity.get("artists") or []
    artists = [
        a.get("name") for a in raw_artists if isinstance(a, dict) and a.get("name")
    ]
    if not artists and entity.get("subtitle"):
        artists = [
            a.strip()
            for a in entity["subtitle"].replace("\xa0", " ").split(",")
            if a.strip()
        ]
    artist_str = ", ".join(artists) if artists else "Unknown Artist"
    cover = _extract_embed_cover(entity)
    rel_iso = (entity.get("releaseDate") or {}).get("isoString") or ""
    year = rel_iso[:4] if len(rel_iso) >= 4 else None
    dur_ms = entity.get("duration") or 0
    duration_s = round(dur_ms / 1000, 1) if dur_ms else None
    return {
        "title": title,
        "artists": artists,
        "artist": artist_str,
        "album": title,
        "cover": cover,
        "year": year,
        "search": f"{artist_str} - {title}",
        "duration_s": duration_s,
        "track_number": 1,
        "total_tracks": 1,
        "track_id": sid,
    }


def _playlist_metas_from_embed(
    sid: str, limit: int | None = None, kind: str = "playlist"
) -> tuple[str, list[dict]]:
    """Fast scraper using Spotify's public embed page without hitting Web API rate limits."""
    entity = _fetch_embed_entity(kind, sid)
    name = entity.get("name") or entity.get("title") or f"spotify-{kind}-{sid}"
    playlist_cover = _extract_embed_cover(entity)
    rel_iso = (entity.get("releaseDate") or {}).get("isoString") or ""
    year = rel_iso[:4] if len(rel_iso) >= 4 else None

    raw_tracks = entity.get("trackList", [])
    selected = raw_tracks[:limit] if limit else raw_tracks
    total = len(selected)

    metas = []
    for idx, t in enumerate(selected, 1):
        title = t.get("title", "Unknown Title")
        artist = (
            t.get("subtitle") or entity.get("subtitle") or "Unknown Artist"
        ).replace("\xa0", " ")
        artists = [a.strip() for a in artist.split(",") if a.strip()]
        uri = t.get("uri") or ""
        track_id = uri.split(":")[-1] if uri and ":" in uri else None
        dur_ms = t.get("duration") or t.get("duration_ms") or 0
        duration_s = round(dur_ms / 1000, 1) if dur_ms else None
        metas.append(
            {
                "title": title,
                "artists": artists,
                "artist": artist,
                "album": name,
                "cover": playlist_cover,
                "year": year,
                "search": f"{artist} - {title}",
                "duration_s": duration_s,
                "track_number": idx,
                "total_tracks": total,
                "uri": uri,
                "track_id": track_id,
                "needs_cover_enrich": kind == "playlist",
            }
        )

    return name, metas


def track_meta(url: str) -> dict:
    kind, sid = parse_url(url)
    if kind != "track":
        raise ValueError(f"Use playlist/album download for {kind} URLs")
    try:
        sp = get_client()
        return _from_track_obj(sp.track(sid), 1, 1)
    except Exception:
        return _track_meta_from_embed(sid)


def _saved_tracks_metas(limit: int | None = None) -> tuple[str, list[dict]]:
    sp = get_user_client(open_browser=False)
    items, offset = [], 0
    while True:
        page = sp.current_user_saved_tracks(offset=offset, limit=50)
        items.extend(page.get("items", []))
        if page.get("next") is None or (limit and len(items) >= limit):
            break
        offset += 50
    selected = items[:limit] if limit else items
    total = len(selected)
    metas = []
    for idx, it in enumerate(selected, 1):
        t = it.get("track")
        if t and t.get("name"):
            metas.append(_from_track_obj(t, idx, total))
    return "Liked Songs", metas


def playlist_metas(url: str, limit: int | None = None) -> tuple[str, list[dict]]:
    _kind, sid = parse_url(url)
    if sid == "liked":
        return _saved_tracks_metas(limit)

    client_candidates = []
    if Path(config.spotify_cache()).exists():
        client_candidates = [lambda: get_user_client(open_browser=False), get_client]
    else:
        client_candidates = [get_client]

    name = None
    items = []
    sp_active = None

    for idx_c, client_fn in enumerate(client_candidates):
        try:
            sp = client_fn()
            pl = sp.playlist(sid, fields="name")
            name = pl.get("name", "spotify-playlist")
            sp_active = sp
            break
        except (SpotifyException, RuntimeError, Exception) as e:
            if (
                idx_c == 0
                and Path(config.spotify_cache()).exists()
                and getattr(e, "http_status", None) in (401, 403)
            ):
                _clear_broken_user_cache()
            continue

    if not sp_active:
        return _playlist_metas_from_embed(sid, limit, kind="playlist")

    offset = 0
    try:
        while True:
            page = sp_active.playlist_items(sid, offset=offset, limit=100)
            batch = page.get("items", [])
            items.extend(batch)
            if page.get("next") is None or (limit and len(items) >= limit):
                break
            offset += 100
    except Exception:
        return _playlist_metas_from_embed(sid, limit, kind="playlist")

    selected = items[:limit] if limit else items
    total = len(selected)
    metas = []
    for idx, it in enumerate(selected, 1):
        t = (it or {}).get("item") or (it or {}).get("track")
        if t and not (it.get("is_local") or t.get("is_local")) and t.get("name"):
            metas.append(_from_track_obj(t, idx, total))

    if not metas:
        return _playlist_metas_from_embed(sid, limit, kind="playlist")

    return name or "spotify-playlist", metas


def album_metas(url: str) -> tuple[str, list[dict]]:
    _, sid = parse_url(url)
    try:
        sp = get_client()
        alb = sp.album(sid)
    except Exception:
        return _playlist_metas_from_embed(sid, kind="album")

    name = alb.get("name", "spotify-album")
    images = alb.get("images", [])
    cover = images[0]["url"] if images else None
    year = (alb.get("release_date") or "")[:4]
    tracks = alb.get("tracks", {}).get("items", [])
    total = len(tracks)

    metas = []
    for idx, t in enumerate(tracks, 1):
        m = _from_track_obj({**t, "album": alb}, idx, total)
        if not m["cover"]:
            m["cover"] = cover
        m["year"] = year
        metas.append(m)
    return name, metas

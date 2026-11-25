import asyncio
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import qrcode
import qrcode.image.svg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import config, downloader, soundcloud, spotify, tags, youtube


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()
    worker_thread = threading.Thread(target=_queue_worker_loop, daemon=True)
    worker_thread.start()
    yield


app = FastAPI(title="spotiyutu Web UI", lifespan=lifespan)
server_port: int = 8765

if hasattr(sys, "_MEIPASS"):
    STATIC_DIR = Path(sys._MEIPASS) / "spotiyutu" / "static"
else:
    STATIC_DIR = Path(__file__).parent / "static"

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)


# Event broadcast queue for Server-Sent Events (SSE)
event_listeners: list[asyncio.Queue] = []
main_loop: asyncio.AbstractEventLoop | None = None

# Active admin authentication tokens
active_admin_tokens: set[str] = set()

# Download Queue management
queue_lock = threading.Lock()
job_queue: list[dict] = []
current_job: dict | None = None
recent_jobs: list[dict] = []


async def broadcast_event(event_type: str, data: dict):
    msg = json.dumps({"type": event_type, "data": data})
    for q in event_listeners:
        try:
            await q.put(msg)
        except Exception:
            pass


def push_event_sync(event_type: str, data: dict):
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(broadcast_event(event_type, data), main_loop)


def get_queue_state() -> dict:
    with queue_lock:
        return {
            "current": current_job,
            "waiting": list(job_queue),
            "recent": list(recent_jobs[:10]),
        }


def _process_single_job(job: dict):
    url = job["url"].strip()
    dest_out = config.out_dir()
    job["status"] = "downloading"
    job["started_at"] = time.time()
    push_event_sync("queue_update", get_queue_state())
    push_event_sync("log", {"text": f"Letöltés indítása: {url}"})

    def on_track_status(
        status_str: str, meta: dict, mp3_path: Path | None, error: str | None = None
    ):
        push_event_sync(
            "track_status",
            {
                "job_id": job["id"],
                "status": status_str,
                "track": meta,
                "file": str(mp3_path.name) if mp3_path else None,
                "error": error,
            },
        )

    def on_progress(completed: int, total: int, meta: dict):
        pct = round((completed / total) * 100, 1) if total else 100
        job["completed"] = completed
        job["total"] = total
        job["percent"] = pct
        job["active_track"] = meta
        if meta.get("playlist_name"):
            job["title"] = meta["playlist_name"]
            push_event_sync("queue_update", get_queue_state())
        push_event_sync(
            "progress",
            {
                "job_id": job["id"],
                "completed": completed,
                "total": total,
                "percent": pct,
                "track": meta,
            },
        )

    try:
        if "open.spotify.com" in url or url.startswith("spotify:") or url == "liked":
            name, files = downloader.download_spotify(
                url,
                out=dest_out,
                limit=job.get("limit"),
                threads=job.get("threads", 3),
                number=job.get("number", False),
                m3u=job.get("m3u", False),
                bitrate=job.get("bitrate", "320"),
                on_progress=on_progress,
                on_track_status=on_track_status,
            )
            saved_folder = dest_out / tags.safe(name) if len(files) > 1 else dest_out
        elif soundcloud.is_soundcloud(url):
            name, files = downloader.download_soundcloud(
                url,
                out=dest_out,
                limit=job.get("limit"),
                threads=job.get("threads", 3),
                number=job.get("number", False),
                m3u=job.get("m3u", False),
                bitrate=job.get("bitrate", "320"),
                on_progress=on_progress,
                on_track_status=on_track_status,
            )
            saved_folder = dest_out / tags.safe(name) if len(files) > 1 else dest_out
        elif "youtube.com" in url or "youtu.be" in url:
            name, files = downloader.download_youtube(
                url,
                out=dest_out,
                limit=job.get("limit"),
                threads=job.get("threads", 3),
                number=job.get("number", False),
                m3u=job.get("m3u", False),
                bitrate=job.get("bitrate", "320"),
                on_progress=on_progress,
                on_track_status=on_track_status,
            )
            saved_folder = dest_out / tags.safe(name) if len(files) > 1 else dest_out
        else:
            mp3 = downloader.download_search(
                url, out=dest_out, bitrate=job.get("bitrate", "320")
            )
            name = mp3.stem
            files = [mp3]
            saved_folder = dest_out
            on_progress(1, 1, {"title": name})

        job["status"] = "done"
        job["title"] = name
        job["file_count"] = len(files)
        job["saved_folder"] = str(saved_folder.resolve())

        push_event_sync(
            "finished",
            {
                "job_id": job["id"],
                "title": name,
                "count": len(files),
                "folder": str(saved_folder.resolve()),
            },
        )
        push_event_sync(
            "log",
            {"text": f"Sikeres letöltés! {len(files)} fájl mentve ide: {saved_folder}"},
        )

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        push_event_sync("error", {"job_id": job["id"], "error": str(e)})
        push_event_sync("log", {"text": f"Hiba történt: {e}"})


def _queue_worker_loop():
    global current_job
    while True:
        job = None
        with queue_lock:
            if job_queue:
                job = job_queue.pop(0)
                current_job = job
        if not job:
            time.sleep(0.5)
            continue

        _process_single_job(job)

        with queue_lock:
            current_job = None
            recent_jobs.insert(0, job)
            if len(recent_jobs) > 30:
                recent_jobs.pop()
        push_event_sync("queue_update", get_queue_state())


# Request Models
class AdminLoginRequest(BaseModel):
    password: str


class SettingsModel(BaseModel):
    out_dir: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    admin_password: str | None = None
    threads: int | None = None
    bitrate: str | None = None
    number: bool | None = None
    m3u: bool | None = None


class PreviewRequest(BaseModel):
    url: str
    limit: int | None = None


class DownloadRequest(BaseModel):
    url: str
    threads: int | None = None
    number: bool | None = None
    m3u: bool | None = None
    bitrate: str | None = None
    limit: int | None = None


class OpenFolderRequest(BaseModel):
    path: str | None = None


def verify_admin(request: Request):
    """Ensure the request is authenticated with admin privileges."""
    token = request.headers.get("X-Admin-Token")
    if token and token in active_admin_tokens:
        return True
    pwd = request.headers.get("X-Admin-Password")
    if pwd and config.verify_admin_password(pwd):
        return True
    raise HTTPException(
        status_code=401, detail="Adminisztrátori jogosultság szükséges!"
    )


# ---------------- API ENDPOINTS ---------------- #


@app.get("/api/status")
def get_status():
    """Public status visible to all guests."""
    return config.get_public_status(port=server_port)


@app.get("/api/qr.svg")
def get_qr_svg(url: str | None = None):
    """Generate dynamic SVG QR Code for current local network access URL."""
    target = url or f"http://{config.get_local_ip()}:{server_port}"
    factory = qrcode.image.svg.SvgImage
    img = qrcode.make(target, image_factory=factory, box_size=10, border=2)
    return Response(
        content=img.to_string(),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/admin/login")
def admin_login(payload: AdminLoginRequest):
    """Authenticate admin with password and return a bearer token."""
    if not config.verify_admin_password(payload.password):
        raise HTTPException(status_code=401, detail="Helytelen jelszó!")
    token = secrets.token_hex(24)
    active_admin_tokens.add(token)
    return {"ok": True, "token": token}


@app.get("/api/admin/check")
def admin_check(request: Request):
    """Check if current session has admin privileges."""
    token = request.headers.get("X-Admin-Token")
    return {"is_admin": bool(token and token in active_admin_tokens)}


@app.post("/api/admin/logout")
def admin_logout(request: Request):
    """Log out admin session."""
    token = request.headers.get("X-Admin-Token")
    if token and token in active_admin_tokens:
        active_admin_tokens.remove(token)
    return {"ok": True}


@app.get("/api/admin/settings")
def get_admin_settings(request: Request):
    """Protected endpoint to view full settings including credentials."""
    verify_admin(request)
    return config.get_all_settings(port=server_port)


@app.post("/api/settings")
def update_settings(payload: SettingsModel, request: Request):
    """Protected endpoint to update settings and admin password."""
    verify_admin(request)
    updated = config.save_settings(
        payload.model_dump(exclude_unset=True), port=server_port
    )
    return updated


@app.post("/api/preview")
def preview(payload: PreviewRequest):
    """Public endpoint to preview Spotify/YouTube metadata."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Üres URL vagy keresőkifejezés!")

    if "open.spotify.com" in url or url.startswith("spotify:") or url == "liked":
        try:
            kind, _sid = spotify.parse_url(url)
            if kind == "track":
                m = spotify.track_meta(url)
                return {
                    "kind": "track",
                    "title": m["title"],
                    "artist": m["artist"],
                    "cover": m.get("cover"),
                    "count": 1,
                    "tracks": [m],
                }
            elif kind == "album":
                name, metas = spotify.album_metas(url)
                cover = metas[0]["cover"] if metas else None
                return {
                    "kind": "album",
                    "title": name,
                    "artist": metas[0]["artist"] if metas else "",
                    "cover": cover,
                    "count": len(metas),
                    "tracks": metas[: payload.limit] if payload.limit else metas,
                }
            else:  # playlist
                name, metas = spotify.playlist_metas(url, limit=payload.limit)
                cover = metas[0]["cover"] if metas else None
                return {
                    "kind": "playlist",
                    "title": name,
                    "artist": f"{len(metas)} zeneszám",
                    "cover": cover,
                    "count": len(metas),
                    "tracks": metas,
                }
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Hiba a Spotify link feldolgozásakor: {e}"
            )

    elif soundcloud.is_soundcloud(url):
        try:
            if "/sets/" in url.lower():
                title, entries = soundcloud.playlist_entries(url, limit=payload.limit)
                cover = entries[0].get("cover") if entries else None
                return {
                    "kind": "soundcloud_set",
                    "title": title,
                    "artist": f"{len(entries)} szám (SoundCloud)",
                    "cover": cover,
                    "count": len(entries),
                    "tracks": entries,
                }
            else:
                m = soundcloud.track_meta(url)
                return {
                    "kind": "soundcloud_track",
                    "title": m["title"],
                    "artist": m["artist"],
                    "cover": m.get("cover"),
                    "count": 1,
                    "tracks": [m],
                }
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Hiba a SoundCloud link feldolgozásakor: {e}"
            )

    elif "youtube.com" in url or "youtu.be" in url:
        try:
            if "list=" in url:
                title, entries = youtube.playlist_entries(url, limit=payload.limit)
                tracks = [
                    {"title": e["title"], "artist": "YouTube", "track_number": i + 1}
                    for i, e in enumerate(entries)
                ]
                return {
                    "kind": "youtube_playlist",
                    "title": title,
                    "artist": f"{len(entries)} videó",
                    "cover": None,
                    "count": len(entries),
                    "tracks": tracks,
                }
            else:
                return {
                    "kind": "youtube_track",
                    "title": url,
                    "artist": "YouTube",
                    "cover": None,
                    "count": 1,
                    "tracks": [{"title": url, "artist": "YouTube", "track_number": 1}],
                }
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Hiba a YouTube link feldolgozásakor: {e}"
            )

    else:
        # Direct search query
        return {
            "kind": "search",
            "title": url,
            "artist": "Keresés",
            "cover": None,
            "count": 1,
            "tracks": [{"title": url, "artist": "Keresés", "track_number": 1}],
        }


@app.get("/api/queue")
def get_queue():
    """Get status of active, waiting, and recent downloads."""
    return get_queue_state()


@app.post("/api/download")
async def start_download(payload: DownloadRequest):
    """Public endpoint: add a download job to the queue."""
    url = payload.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Üres URL!")

    title_guess = url
    # Quick title simplification for queue display
    if "track/" in url:
        title_guess = "Spotify dal..."
    elif "playlist/" in url:
        title_guess = "Spotify lejátszási lista..."
    elif "album/" in url:
        title_guess = "Spotify album..."
    elif soundcloud.is_soundcloud(url):
        title_guess = "SoundCloud zene..."
    elif "youtube.com" in url or "youtu.be" in url:
        title_guess = "YouTube hang..."

    defaults = config.default_download_options()
    threads = payload.threads if payload.threads is not None else defaults["threads"]
    bitrate = payload.bitrate if payload.bitrate is not None else defaults["bitrate"]
    number = payload.number if payload.number is not None else defaults["number"]
    m3u = payload.m3u if payload.m3u is not None else defaults["m3u"]

    job = {
        "id": str(uuid.uuid4())[:8],
        "url": url,
        "threads": threads,
        "number": number,
        "m3u": m3u,
        "bitrate": bitrate,
        "limit": payload.limit,
        "status": "waiting",
        "created_at": time.time(),
        "title": title_guess,
        "completed": 0,
        "total": 0,
        "percent": 0,
    }

    with queue_lock:
        job_queue.append(job)
        position = len(job_queue)

    push_event_sync("queue_update", get_queue_state())
    push_event_sync(
        "log", {"text": f"Hozzáadva a letöltési sorhoz ({position}. pozíció): {url}"}
    )

    return {
        "status": "queued",
        "job_id": job["id"],
        "position": position,
        "title": title_guess,
    }


@app.get("/api/events")
async def events():
    """Server-Sent Events (SSE) for real-time progress and queue notifications."""
    q = asyncio.Queue()
    event_listeners.append(q)

    async def event_generator():
        try:
            # Send initial ping and queue state
            init_data = json.dumps(
                {
                    "type": "init",
                    "data": {
                        "queue": get_queue_state(),
                        "status": config.get_public_status(port=server_port),
                    },
                }
            )
            yield f"data: {init_data}\n\n"

            while True:
                data = await q.get()
                yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if q in event_listeners:
                event_listeners.remove(q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/open-folder")
def open_folder(payload: OpenFolderRequest, request: Request):
    """Protected endpoint to open folder in OS file manager (host only)."""
    verify_admin(request)
    folder_path = Path(payload.path) if payload.path else config.out_dir()
    if not folder_path.exists():
        folder_path.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(folder_path.resolve()))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder_path.resolve())], check=False)
        else:
            subprocess.run(["xdg-open", str(folder_path.resolve())], check=False)
        return {"status": "opened", "path": str(folder_path.resolve())}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Nem sikerült megnyitni a mappát: {e}"
        )


@app.post("/api/login")
def login_spotify(request: Request):
    """Protected endpoint to trigger Spotify OAuth login in browser."""
    verify_admin(request)
    try:
        sp = spotify.get_user_client(open_browser=True)
        me = sp.me()
        return {"status": "ok", "user": me.get("display_name"), "id": me.get("id")}
    except Exception as e:
        spotify._clear_broken_user_cache()
        err_msg = str(e)
        if "403" in err_msg or "not registered" in err_msg.lower():
            raise HTTPException(
                status_code=400,
                detail=(
                    "A Spotify Developer alkalmazásban ez a fiók nincs regisztrálva (403). "
                    "Nyilvános dalok, albumok és lejátszási listák letöltéséhez NEM szükséges a bejelentkezés!"
                ),
            )
        raise HTTPException(status_code=500, detail=f"Spotify bejelentkezési hiba: {e}")


@app.get("/", response_class=HTMLResponse)
def index():
    html_file = STATIC_DIR / "index.html"
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>spotiyutu index.html not found</h1>"

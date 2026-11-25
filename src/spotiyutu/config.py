import os
import socket
import sys
from pathlib import Path

from dotenv import load_dotenv


def get_app_dir() -> Path:
    """Return directory of executable (if bundled) or current working directory."""
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).parent
    return Path.cwd()


# Load .env from app directory if present
ENV_PATH = get_app_dir() / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()


def out_dir() -> Path:
    """Return download directory. Defaults to ./downloads next to script/exe."""
    raw = os.getenv("SPOTIYUTU_OUT", "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = get_app_dir() / p
    else:
        p = get_app_dir() / "downloads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_local_ip() -> str:
    """Determine the LAN IP address of this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        try:
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def admin_password() -> str:
    """Return the admin password, defaulting to 'admin'."""
    return os.getenv("SPOTIYUTU_PASSWORD", "admin")


def verify_admin_password(candidate: str) -> bool:
    """Check if provided password matches admin password."""
    return bool(candidate and candidate == admin_password())


def spotify_creds() -> tuple[str | None, str | None]:
    return os.getenv("SPOTIPY_CLIENT_ID"), os.getenv("SPOTIPY_CLIENT_SECRET")


def spotify_redirect() -> str:
    return os.getenv("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback")


def spotify_cache() -> str:
    cache_name = os.getenv("SPOTIPY_CACHE", ".spotify_cache")
    p = Path(cache_name)
    if not p.is_absolute():
        p = get_app_dir() / p
    return str(p)


def get_ffmpeg_dir() -> str | None:
    import shutil

    # 1. Check PyInstaller bundled temp folder (_MEIPASS)
    if hasattr(sys, "_MEIPASS"):
        meipass_path = Path(sys._MEIPASS)
        if (meipass_path / "ffmpeg.exe").exists():
            return str(meipass_path)

    # 2. Check executable/app folder (portable / alongside exe)
    app_dir = get_app_dir()
    if (app_dir / "ffmpeg.exe").exists():
        return str(app_dir)
    if (app_dir / "ffmpeg" / "ffmpeg.exe").exists():
        return str(app_dir / "ffmpeg")

    # 3. Check system PATH
    loc = shutil.which("ffmpeg")
    if loc:
        return str(Path(loc).parent)

    # 4. Check imageio-ffmpeg bundled binary
    try:
        import imageio_ffmpeg

        exe_raw = imageio_ffmpeg.get_ffmpeg_exe()
        if exe_raw and Path(exe_raw).exists():
            exe_p = Path(exe_raw)
            bin_dir = exe_p.parent
            named_ffmpeg = bin_dir / "ffmpeg.exe"
            if not named_ffmpeg.exists():
                try:
                    shutil.copy(exe_p, named_ffmpeg)
                except Exception:
                    pass
            os.environ["PATH"] = f"{bin_dir};" + os.environ.get("PATH", "")
            return str(bin_dir)
    except Exception:
        pass

    # 5. Check common installation locations (e.g. WinGet packages, Program Files)
    candidates = []
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Microsoft" / "WinGet" / "Packages")
    candidates.append(Path("C:/Program Files/ffmpeg/bin"))

    for base in candidates:
        if base.exists():
            for exe in base.rglob("ffmpeg.exe"):
                bin_dir = str(exe.parent)
                os.environ["PATH"] = f"{bin_dir};" + os.environ.get("PATH", "")
                return bin_dir
    return None


def check_ffmpeg() -> bool:
    return get_ffmpeg_dir() is not None


def get_ffmpeg_exe() -> str | None:
    """Return the absolute path to ffmpeg.exe binary."""
    d = get_ffmpeg_dir()
    if d:
        p = Path(d) / "ffmpeg.exe"
        if p.exists():
            return str(p)
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def get_public_status(port: int = 8765) -> dict:
    """Public status visible to all guests - does NOT leak secrets or passwords."""
    cid, sec = spotify_creds()
    cache_file = Path(spotify_cache())
    local_ip = get_local_ip()
    target_out = out_dir()
    return {
        "has_ffmpeg": check_ffmpeg(),
        "has_spotify_creds": bool(cid and sec),
        "is_logged_in": cache_file.exists() and cache_file.stat().st_size > 10,
        "local_ip": local_ip,
        "port": port,
        "lan_url": f"http://{local_ip}:{port}",
        "out_dir_display": str(target_out),
        "out_dir_name": target_out.name,
        "is_password_default": admin_password() == "admin",
    }


def default_download_options() -> dict:
    """Default download settings: 3 threads, 320 kbps, no track numbering, no m3u."""
    return {
        "threads": int(os.getenv("SPOTIYUTU_THREADS", "3")),
        "bitrate": os.getenv("SPOTIYUTU_BITRATE", "320"),
        "number": os.getenv("SPOTIYUTU_NUMBER", "false").lower()
        in ("true", "1", "yes"),
        "m3u": os.getenv("SPOTIYUTU_M3U", "false").lower() in ("true", "1", "yes"),
    }


def get_all_settings(port: int = 8765) -> dict:
    """Full settings for authenticated admin."""
    cid, sec = spotify_creds()
    pub = get_public_status(port=port)
    opts = default_download_options()
    return {
        **pub,
        "out_dir": str(out_dir().resolve()),
        "client_id": cid or "",
        "client_secret": sec or "",
        "redirect_uri": spotify_redirect(),
        "has_custom_password": os.getenv("SPOTIYUTU_PASSWORD") is not None
        and os.getenv("SPOTIYUTU_PASSWORD") != "admin",
        "threads": opts["threads"],
        "bitrate": opts["bitrate"],
        "number": opts["number"],
        "m3u": opts["m3u"],
    }


def save_settings(new_settings: dict, port: int = 8765) -> dict:
    """Save settings to .env file in app directory."""
    env_file = get_app_dir() / ".env"
    current_lines = (
        env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else []
    )
    keys_map = {
        "out_dir": "SPOTIYUTU_OUT",
        "client_id": "SPOTIPY_CLIENT_ID",
        "client_secret": "SPOTIPY_CLIENT_SECRET",
        "redirect_uri": "SPOTIPY_REDIRECT_URI",
        "admin_password": "SPOTIYUTU_PASSWORD",
        "threads": "SPOTIYUTU_THREADS",
        "bitrate": "SPOTIYUTU_BITRATE",
        "number": "SPOTIYUTU_NUMBER",
        "m3u": "SPOTIYUTU_M3U",
    }
    env_data = {}
    for line in current_lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_data[k.strip()] = v.strip()

    for setting_key, env_key in keys_map.items():
        if setting_key in new_settings and new_settings[setting_key] is not None:
            val = str(new_settings[setting_key]).strip()
            if isinstance(new_settings[setting_key], bool):
                val = "true" if new_settings[setting_key] else "false"
            if val or setting_key == "out_dir":
                env_data[env_key] = val
                os.environ[env_key] = val

    out_lines = [f"{k}={v}" for k, v in env_data.items()]
    env_file.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return get_all_settings(port=port)

import subprocess
import sys
import zipfile
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from spotiyutu import config


def build():
    print("=" * 60)
    print("Spotiyutu - Windows Executable (.exe) Build")
    print("=" * 60)

    ffmpeg_dir = config.get_ffmpeg_dir()
    if not ffmpeg_dir:
        raise RuntimeError(
            "Nem található ffmpeg.exe! Kérlek telepítsd vagy állítsd be."
        )

    ffmpeg_exe = Path(ffmpeg_dir) / "ffmpeg.exe"
    ffprobe_exe = Path(ffmpeg_dir) / "ffprobe.exe"

    if not ffmpeg_exe.exists() or not ffprobe_exe.exists():
        raise RuntimeError(
            f"Hiányzik az ffmpeg.exe vagy ffprobe.exe a mappából: {ffmpeg_dir}"
        )

    print(f"[+] FFmpeg binárisok észlelve: {ffmpeg_dir}")

    static_dir = Path("src/spotiyutu/static").resolve()
    if not static_dir.exists():
        raise RuntimeError(f"Hiányzik a statikus könyvtár: {static_dir}")

    print(f"[+] Statikus UI könyvtár: {static_dir}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "spotiyutu",
        "--add-data",
        f"{static_dir};spotiyutu/static",
        "--add-binary",
        f"{ffmpeg_exe};.",
        "--add-binary",
        f"{ffprobe_exe};.",
        "--paths",
        "src",
        "--hidden-import",
        "spotiyutu",
        "--hidden-import",
        "spotiyutu.ui",
        "--hidden-import",
        "spotiyutu.cli",
        "--hidden-import",
        "spotiyutu.config",
        "--hidden-import",
        "spotiyutu.downloader",
        "--hidden-import",
        "spotiyutu.spotify",
        "--hidden-import",
        "spotiyutu.tags",
        "--hidden-import",
        "spotiyutu.youtube",
        "--hidden-import",
        "spotiyutu.soundcloud",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops",
        "--hidden-import",
        "uvicorn.loops.auto",
        "--hidden-import",
        "uvicorn.protocols",
        "--hidden-import",
        "uvicorn.protocols.http",
        "--hidden-import",
        "uvicorn.protocols.http.auto",
        "--hidden-import",
        "uvicorn.lifespan",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "spotipy",
        "--hidden-import",
        "yt_dlp",
        "--hidden-import",
        "mutagen",
        "--hidden-import",
        "qrcode",
        "--hidden-import",
        "qrcode.image.svg",
        "--copy-metadata",
        "yt-dlp",
        "--copy-metadata",
        "spotipy",
        "--copy-metadata",
        "qrcode",
        "src/spotiyutu/__main__.py",
    ]

    print("\n[+] PyInstaller futtatása...\n" + " ".join(cmd) + "\n")
    res = subprocess.run(cmd, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build sikertelen, hibakód: {res.returncode}")

    dist_exe = Path("dist/spotiyutu.exe")
    if not dist_exe.exists():
        raise RuntimeError("Nem jött létre a dist/spotiyutu.exe fájl!")

    size_mb = dist_exe.stat().st_size / (1024 * 1024)
    print(f"\n[OK] SIKERES BUILD! Fajl: {dist_exe.resolve()} ({size_mb:.1f} MB)")

    # Create portable ZIP archive
    zip_path = Path("dist/spotiyutu-windows-portable.zip")
    print(f"\n[+] Hordozhato ZIP keszitese: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(dist_exe, arcname="spotiyutu.exe")
        readme = Path("README.md")
        if readme.exists():
            zf.write(readme, arcname="README.md")

    zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"[OK] ZIP archivum elkeszult: {zip_path.resolve()} ({zip_size_mb:.1f} MB)")
    print(
        "\nKesz! Ezt a fajlt vagy a ZIP-et barmelyik masik Windows PC-re atmasolhatod!"
    )


if __name__ == "__main__":
    build()

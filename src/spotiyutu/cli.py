import sys
import threading
import time
import webbrowser
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import typer
from rich import print
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)

from . import config, downloader, soundcloud

app = typer.Typer(help="spotiyutu: Spotify + YouTube -> mp3 320k")


@app.command()
def download(
    inp: str = typer.Argument(
        ..., help="Spotify track/playlist/album, YouTube link vagy keresés"
    ),
    out: str = typer.Option("", "--out", "-o", help="Célmappa felülbírálása"),
    limit: int = typer.Option(
        0, "--limit", "-l", help="Maximális letöltési darabszám (0 = mind)"
    ),
    threads: int = typer.Option(
        3, "--threads", "-t", help="Párhuzamos szálak száma (1-8)"
    ),
    number: bool = typer.Option(
        False, "--number/--no-number", help="Sorszám hozzáadása a fájlnévhez"
    ),
    m3u: bool = typer.Option(
        False, "--m3u/--no-m3u", help=".m3u lejátszási lista fájl létrehozása"
    ),
    bitrate: str = typer.Option(
        "320", "--bitrate", "-b", help="MP3 bitráta (320, 256, 192)"
    ),
):
    """Auto-detect: spotify track/playlist/album | youtube video/playlist | search."""
    dest = Path(out) if out else config.out_dir()
    lim = limit or None

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40, complete_style="green", finished_style="bold green"),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task_id = progress.add_task("[cyan]Letöltés előkészítése...", total=1)

        def on_prog(completed: int, total: int, m: dict):
            progress.update(task_id, total=total, completed=completed)
            desc = m.get("title") or m.get("search") or m.get("url") or "Feldolgozás"
            progress.update(task_id, description=f"[cyan]{desc[:35]}")

        def on_track(
            status_str: str, m: dict, mp3_path: Path | None, error: str | None = None
        ):
            title = m.get("title") or "Dal"
            if status_str == "done":
                progress.console.print(
                    f" [green][OK][/green] Kész: [bold]{title}[/bold]"
                )
            elif status_str == "skipped":
                progress.console.print(f" [dim][SKIP][/dim] Már létezik: {title}")
            elif status_str == "error":
                progress.console.print(f" [red][HIBA][/red] {title} ({error})")

        if "open.spotify.com" in inp or inp.startswith("spotify:") or inp == "liked":
            _name, files = downloader.download_spotify(
                inp,
                dest,
                lim,
                threads=threads,
                number=number,
                m3u=m3u,
                bitrate=bitrate,
                on_progress=on_prog,
                on_track_status=on_track,
            )
        elif soundcloud.is_soundcloud(inp):
            _name, files = downloader.download_soundcloud(
                inp,
                dest,
                lim,
                threads=threads,
                number=number,
                m3u=m3u,
                bitrate=bitrate,
                on_progress=on_prog,
                on_track_status=on_track,
            )
        elif "youtube.com" in inp or "youtu.be" in inp:
            _name, files = downloader.download_youtube(
                inp,
                dest,
                lim,
                threads=threads,
                number=number,
                m3u=m3u,
                bitrate=bitrate,
                on_progress=on_prog,
                on_track_status=on_track,
            )
        else:
            mp3 = downloader.download_search(inp, dest, bitrate=bitrate)
            files = [mp3]
            on_prog(1, 1, {"title": inp})

    print(f"\n[bold green]Sikeres letöltés![/bold green] Összesen {len(files)} fájl:")
    for f in files:
        print(f"  [cyan]{f}[/cyan]")


@app.command()
def ui(
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        "-h",
        help="Kiszolgáló IP címe (0.0.0.0 a helyi hálózathoz)",
    ),
    port: int = typer.Option(8765, "--port", "-p", help="Kiszolgáló portja"),
    open_browser: bool = typer.Option(
        True, "--open/--no-open", help="Böngésző automatikus megnyitása"
    ),
):
    """Start modern Web UI with real-time progress bar, queue and LAN party mode."""
    import uvicorn

    from . import ui as ui_module

    ui_module.server_port = port

    local_ip = config.get_local_ip()
    lan_url = f"http://{local_ip}:{port}"
    browser_url = (
        f"http://localhost:{port}"
        if host in ("0.0.0.0", "127.0.0.1")
        else f"http://{host}:{port}"
    )

    if open_browser:

        def _open():
            time.sleep(1.2)
            webbrowser.open(browser_url)

        threading.Thread(target=_open, daemon=True).start()

    out_folder = config.out_dir()
    is_default_pwd = config.admin_password() == "admin"
    pwd_info = (
        "[yellow]admin[/yellow] [dim](alapértelmezett, a felületen módosítható)[/dim]"
        if is_default_pwd
        else "[green]Egyéni jelszó aktív[/green]"
    )

    banner = (
        f"[bold green]Spotiyutu Szerver & Vendég Mód elindult![/bold green]\n\n"
        f"  💻 [bold white]Helyi gép (Host):[/bold white]       [cyan]{browser_url}[/cyan]\n"
        f"  📱 [bold white]Helyi hálózat (LAN/Wi-Fi):[/bold white] [bold yellow]{lan_url}[/bold yellow]\n"
        f"  📁 [bold white]Letöltési mappa:[/bold white]          [dim]{out_folder}[/dim]\n"
        f"  🔒 [bold white]Admin jelszó:[/bold white]             {pwd_info}\n\n"
        f"[dim]👉 A vendégek a fenti LAN linken vagy az oldal alján lévő QR-kódon keresztül tölthetnek be dalokat!\n"
        f"   Az adminisztrátori beállítások és a mappa megnyitása jelszóval védett.[/dim]"
    )
    print()
    print(Panel(banner, title="🎵 SPOTIYUTU VENDÉG MÓD", border_style="bright_green"))
    print()

    uvicorn.run(ui_module.app, host=host, port=port, log_level="info")


@app.command()
def setup():
    """Diagnosztika: beállítások, Spotify kulcsok, jelszó és ffmpeg állapotának ellenőrzése."""
    cfg = config.get_all_settings()
    print(
        f"Spotify ID: {'[green]OK[/green]' if cfg['client_id'] else '[red]HIÁNYZIK[/red]'}"
    )
    print(
        f"Spotify Secret: {'[green]OK[/green]' if cfg['client_secret'] else '[red]HIÁNYZIK[/red]'}"
    )
    print(
        f"Spotify Bejelentkezés: {'[green]BEJELENTKEZVE[/green]' if cfg['is_logged_in'] else '[yellow]NINCS BEJELENTKEZVE[/yellow]'}"
    )
    print(f"Redirect URI: {cfg['redirect_uri']}")
    print(
        f"FFmpeg: {'[green]OK[/green]' if cfg['has_ffmpeg'] else '[red]HIÁNYZIK[/red]'}"
    )
    print(f"Célmappa: [cyan]{cfg['out_dir']}[/cyan]")
    print(f"Helyi IP (LAN): [yellow]{cfg['local_ip']}[/yellow]")
    print(
        f"Admin jelszó: {'[green]Egyéni[/green]' if cfg['has_custom_password'] else '[yellow]Alapértelmezett (admin)[/yellow]'}"
    )


@app.command()
def login():
    """Egyszeri Spotify felhasználói bejelentkezés privát listákhoz."""
    from . import spotify

    sp = spotify.get_user_client()
    me = sp.me()
    print(
        f"[green]Sikeres bejelentkezés:[/green] {me.get('display_name')} ({me.get('id')})"
    )


if __name__ == "__main__":
    app()

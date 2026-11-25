# Spotiyutu 🎵

> Spotify, YouTube és SoundCloud audio letöltő, garantált 320 kbps MP3 konvertáló, sorszámozás, M3U készítés és modern Web UI helyi hálózati vendég móddal.

---

## Főbb funkciók

- 🌐 **Modern grafikus felület & Helyi Hálózati Vendég Mód (LAN Party Mode)**:
  - Böngészőben futó, reszponzív, sötét tónusú felület (`spotiyutu ui`).
  - **Vendég mód helyi hálózaton**: A vendégek a telefonjukról megnyithatják az oldalt, Spotify, YouTube és SoundCloud linkeket adhatnak hozzá, amik a háttérben letöltődnek a szerverre.
  - **Beépített dinamikus QR-kód**: Az oldal alján megjelenő QR-kód azonnal beolvasható telefonos kamerával a gyors megosztáshoz.
  - **Jelszóval védett admin felület**: A letöltési mappa és a Spotify API kulcsok jelszóval el vannak zárva a vendégek elől (alapértelmezett: `admin`).
  - **Letöltési sor (Queue)**: Több vendég párhuzamos beküldése esetén a rendszer sorba állítja és egymás után letölti a dalokat.
  - Valós idejű, animált folyamatjelző (progress bar) és élő státuszfrissítés (SSE).
  - Lejátszási lista borítókép és daltáblázat előnézet letöltés előtt.
  - "Mappa megnyitása" gomb a Windows Intéző közvetlen megnyitásához (admin hitelesítéssel).
- 🎧 **SoundCloud & YouTube & Spotify támogatás**:
  - Közvetlen SoundCloud dalok és lejátszási listák (`sets`) letöltése.
  - YouTube videók és lejátszási listák letöltése.
  - Spotify dalok, albumok, lejátszási listák és kedvelt dalok metaadat-alapú letöltése.
  - **Garantált MP3 kimenet**: A beépített FFmpeg motornak és automatikus utókonvertálásnak köszönhetően minden hanganyag valódi 320 kbps MP3 formátumban kerül mentésre (nincs nyers webm vagy m4a).
- ⚡ **Párhuzamos, többszálas letöltés**:
  - Állítható szálkezelés (1-8 szál, alapértelmezett 3), amellyel a hosszú listák többszörösen gyorsabban töltődnek le.
- 🔄 **Kettős Spotify motor (API + Embed Fallback)**:
  - Támogatja a privát listákat (OAuth bejelentkezéssel).
  - Támogatja a hivatalos / szerkesztőségi listákat és toplistákat (pl. *Today's Top Hits*, *RapCaviar*) egy automatikus embed scraper fallback segítségével (megkerülve a Spotify 2024-2026-os API korlátozásait és 404-es hibáit).
  - Támogatja a lokalizált nemzetközi linkeket (`intl-hu`, `intl-en`, stb.) és a Spotify URI formátumot (`spotify:playlist:...`).
- 📁 **Rendezett zenei mappák**:
  - Automatikus sorszámozás a fájlnevekben (`01 - Előadó - Cím.mp3`), így a fájlkezelőkben és autós fejegységeken a dalok a lista sorrendjében játszódnak le.
  - Automatikus `.m3u` lejátszási lista fájl létrehozása a mappában.
- 🏷️ **Teljes ID3 metaadat és borítókép**:
  - Cím (`TIT2`), előadó (`TPE1`), album (`TALB`), sorszám (`TRCK`, pl. `1/25`), megjelenési év (`TDRC`) és beágyazott borítókép (`APIC`).
- ⏭️ **Intelligens átugrás (Skip)**:
  - Ha egy dal már korábban letöltésre került, a rendszer azonnal felismeri és nem tölti le újra.

---

## Használat

### 🚀 Önálló Windows Program (.exe) – Másik PC-n való használathoz!

Az alkalmazásból készült egy **100%-ban önálló, hordozható Windows futtatható fájl**, amely tartalmazza a Python környezetet, az összes könyvtárat, a statikus felületet és az **FFmpeg** binárisokat is.

- **Fájl helye:** [`dist/spotiyutu.exe`](file:///s:/Etc%20projekt/spotiyutu/spotiyutu/dist/spotiyutu.exe) (vagy a tömörített [`dist/spotiyutu-windows-portable.zip`](file:///s:/Etc%20projekt/spotiyutu/spotiyutu/dist/spotiyutu-windows-portable.zip))
- **Használat másik PC-n:** Csak másold át a pendrive-ra vagy küldd át a `spotiyutu.exe` fájlt. A célgépen **semmit sem kell telepíteni** (nem szükséges Python, git vagy FFmpeg).
- **Indítás:** Duplán kattints a `spotiyutu.exe` fájlra az Intézőben, és a böngésződben azonnal betöltődik a grafikus kezelőfelület!

---

### 1. Grafikus felület indítása (Fejlesztői környezetből)

```powershell
uv run spotiyutu ui
```
*A parancs automatikusan megnyitja a böngésződben a kezelőfelületet (`http://localhost:8765`), valamint a terminálban kiírja a helyi hálózati elérési címet (pl. `http://192.168.1.50:8765`), amit a telefonodon megnyitva rögtön bemutathatod a QR-kódot a vendégeknek!*


---

### 2. Parancssori használat (CLI)

#### Lejátszási lista letöltése:
```powershell
# Teljes lista letöltése
uv run spotiyutu download "https://open.spotify.com/playlist/69KOgR9Wzeqsv96nX1BLOh"

# Első 5 dal letöltése 4 szálon
uv run spotiyutu download "https://open.spotify.com/intl-hu/playlist/69KOgR9Wzeqsv96nX1BLOh" --limit 5 --threads 4
```

#### Egyéb lehetőségek:
```powershell
# Állapot és diagnosztika (FFmpeg, Spotify kulcsok, bejelentkezés)
uv run spotiyutu setup

# Spotify fiók összekapcsolása privát listákhoz
uv run spotiyutu login

# YouTube videó vagy lista letöltése
uv run spotiyutu download "https://www.youtube.com/watch?v=..."

# Közvetlen keresés és letöltés
uv run spotiyutu download "Előadó neve - Dal címe"
```

---

## CLI Kapcsolók

| Kapcsoló | Rövidítés | Leírás | Alapértelmezett |
| :--- | :--- | :--- | :--- |
| `--out` | `-o` | Célmappa felülbírálása | `./downloads` |
| `--limit` | `-l` | Letöltendő dalok maximális száma (0 = mind) | `0` |
| `--threads` | `-t` | Párhuzamos letöltési szálak száma (1-8) | `3` |
| `--number / --no-number` | | Sorszám előtag a fájlnévben (`01 - ...`) | `True` |
| `--m3u / --no-m3u` | | `.m3u` lejátszási lista fájl létrehozása | `True` |
| `--bitrate` | `-b` | MP3 minőség / bitráta (320, 256, 192) | `320` |

---

## Fejlesztés és Tesztelés

```powershell
# Egységtesztek futtatása
uv run pytest -v

# Kódellenőrzés (Ruff linter)
uv run ruff check
```


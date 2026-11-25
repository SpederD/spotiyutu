import pytest

from spotiyutu import tags
from spotiyutu.spotify import parse_url


def test_parse_url_standard():
    assert parse_url("https://open.spotify.com/track/1234567890abcdefABCDEF") == (
        "track",
        "1234567890abcdefABCDEF",
    )
    assert parse_url("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M") == (
        "playlist",
        "37i9dQZF1DXcBWIGoYBM5M",
    )
    assert parse_url("https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy") == (
        "album",
        "4aawyAB9vmqN3uQ7FjRGTy",
    )


def test_parse_url_with_query_params():
    assert parse_url(
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=e2fbc44654b94f10"
    ) == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")


def test_parse_url_intl():
    assert parse_url(
        "https://open.spotify.com/intl-hu/playlist/37i9dQZF1DXcBWIGoYBM5M"
    ) == ("playlist", "37i9dQZF1DXcBWIGoYBM5M")
    assert parse_url(
        "https://open.spotify.com/intl-de/track/1234567890abcdefABCDEF?si=xyz"
    ) == ("track", "1234567890abcdefABCDEF")


def test_parse_url_uri():
    assert parse_url("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M") == (
        "playlist",
        "37i9dQZF1DXcBWIGoYBM5M",
    )
    assert parse_url("spotify:track:1234567890abcdefABCDEF") == (
        "track",
        "1234567890abcdefABCDEF",
    )


def test_parse_url_invalid():
    with pytest.raises(ValueError):
        parse_url("https://example.com/not-spotify")


def test_tags_safe():
    # Forbidden Windows / Unix characters: < > : " / \ | ? *
    assert tags.safe('Test: "Song" / <Remix>? *Yes*') == "Test_ _Song_ _ _Remix__ _Yes_"
    # Accented unicode characters should be preserved
    assert "áéíóöőúüű" in tags.safe("Zeneszám - áéíóöőúüű")
    # Empty string fallback
    assert tags.safe("") == "unnamed"


def test_m3u_generation(tmp_path):
    from spotiyutu.downloader import _write_m3u

    p1 = tmp_path / "01 - Artist - Song1.mp3"
    p2 = tmp_path / "02 - Artist - Song2.mp3"
    p1.touch()
    p2.touch()

    _write_m3u(tmp_path, "My Cool Playlist", [p1, p2])
    m3u_file = tmp_path / "My Cool Playlist.m3u"
    assert m3u_file.exists()
    content = m3u_file.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "01 - Artist - Song1.mp3" in content
    assert "02 - Artist - Song2.mp3" in content

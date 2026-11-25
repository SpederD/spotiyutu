from pathlib import Path

from fastapi.testclient import TestClient

from spotiyutu import config, soundcloud
from spotiyutu.ui import app


def test_local_ip_detection():
    ip = config.get_local_ip()
    assert isinstance(ip, str)
    assert len(ip.split(".")) == 4


def test_default_downloads_folder(monkeypatch):
    monkeypatch.delenv("SPOTIYUTU_OUT", raising=False)
    target = config.out_dir()
    assert isinstance(target, Path)
    assert target.exists()
    assert "downloads" in str(target).lower()


def test_admin_password_verification(monkeypatch):
    monkeypatch.setenv("SPOTIYUTU_PASSWORD", "secret123")
    assert config.verify_admin_password("secret123") is True
    assert config.verify_admin_password("wrong") is False
    assert config.verify_admin_password("") is False


def test_public_status_no_secrets():
    status = config.get_public_status(port=8765)
    assert "lan_url" in status
    assert "local_ip" in status
    assert "client_secret" not in status
    assert "SPOTIYUTU_PASSWORD" not in status


def test_api_status_and_qr():
    client = TestClient(app)
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "lan_url" in data
    assert "client_secret" not in data

    qr_res = client.get("/api/qr.svg")
    assert qr_res.status_code == 200
    assert "image/svg+xml" in qr_res.headers.get("content-type", "")
    assert "<svg" in qr_res.text


def test_admin_auth_endpoints(monkeypatch):
    monkeypatch.setenv("SPOTIYUTU_PASSWORD", "party_pass_99")
    client = TestClient(app)

    # Wrong password should fail
    fail_res = client.post("/api/admin/login", json={"password": "bad_password"})
    assert fail_res.status_code == 401

    # Protected endpoint without token should fail
    unauth_res = client.get("/api/admin/settings")
    assert unauth_res.status_code == 401

    # Correct login should give token
    login_res = client.post("/api/admin/login", json={"password": "party_pass_99"})
    assert login_res.status_code == 200
    token = login_res.json()["token"]

    # Access protected settings with token
    settings_res = client.get("/api/admin/settings", headers={"X-Admin-Token": token})
    assert settings_res.status_code == 200
    assert "out_dir" in settings_res.json()


def test_download_queue():
    client = TestClient(app)
    # Add a track to queue
    res = client.post(
        "/api/download",
        json={
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "threads": 2,
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert "job_id" in data

    # Check queue endpoint
    q_res = client.get("/api/queue")
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert "waiting" in q_data or "current" in q_data


def test_ffmpeg_detected():
    assert config.check_ffmpeg() is True
    exe = config.get_ffmpeg_exe()
    assert exe is not None
    assert Path(exe).exists()


def test_soundcloud_url():
    assert soundcloud.is_soundcloud("https://soundcloud.com/artist/track") is True
    assert soundcloud.is_soundcloud("https://on.soundcloud.com/xyz123") is True
    assert soundcloud.is_soundcloud("https://open.spotify.com/track/123") is False
    assert soundcloud.is_soundcloud("https://www.youtube.com/watch?v=123") is False

"""
Tests for the LoopNet email/password login endpoint (/api/loopnet/login)
and the credentials store in scrapers.loopnet_auth.

The actual Playwright browser login is always mocked — LoopNet is not
reachable from CI/codespace (Akamai IP denylist, see REGOG_REBUILD_V8.md §15).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

import app as webapp  # noqa: E402  (web/app.py)
from scrapers import loopnet_auth  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Flask test client with session/credentials paths redirected to tmp."""
    monkeypatch.setattr(webapp, "LOOPNET_SESSION_PATH", tmp_path / "session.json")
    monkeypatch.setattr(webapp, "LOOPNET_CREDENTIALS_PATH", tmp_path / "creds.json")
    webapp.app.config["TESTING"] = True
    with webapp.app.test_client() as c:
        yield c


def _fake_session(cookies=None):
    cookies = cookies or {"SessionFarm_GUID": "g", "UserPreferences": "p",
                          "UserInfo_AssociateID": "a"}
    return loopnet_auth._build_session(cookies)


def test_login_requires_email(client):
    resp = client.post("/api/loopnet/login", json={"password": "x"})
    assert resp.status_code == 400
    assert "email" in resp.get_json()["error"].lower()


def test_login_requires_valid_email(client):
    resp = client.post("/api/loopnet/login",
                       json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 400


def test_login_requires_password(client):
    resp = client.post("/api/loopnet/login", json={"email": "a@b.com"})
    assert resp.status_code == 400
    assert "password" in resp.get_json()["error"].lower()


def test_login_success_saves_session_and_credentials(client, monkeypatch, tmp_path):
    def fake_login(email, password, session_path=None, **kw):
        with open(session_path, "w") as f:
            json.dump(_fake_session(), f)
        return _fake_session()

    monkeypatch.setattr(loopnet_auth, "login_with_credentials", fake_login)

    resp = client.post("/api/loopnet/login",
                       json={"email": "a@b.com", "password": "secret"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "logged_in"
    assert data["cookie_count"] == 3
    assert data["missing_expected"] == []
    # Credentials remembered by default
    creds = json.loads((tmp_path / "creds.json").read_text())
    assert creds == {"email": "a@b.com", "password": "secret"}


def test_login_remember_false_skips_credentials(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        loopnet_auth, "login_with_credentials",
        lambda email, password, session_path=None, **kw: _fake_session(),
    )
    resp = client.post("/api/loopnet/login",
                       json={"email": "a@b.com", "password": "s", "remember": False})
    assert resp.status_code == 200
    assert not (tmp_path / "creds.json").exists()


def test_login_blocked_ip_returns_502(client, monkeypatch):
    def fake_login(email, password, session_path=None, **kw):
        raise loopnet_auth.LoopNetLoginError("IP is denylisted", reason="blocked")

    monkeypatch.setattr(loopnet_auth, "login_with_credentials", fake_login)
    resp = client.post("/api/loopnet/login",
                       json={"email": "a@b.com", "password": "s"})
    assert resp.status_code == 502
    assert resp.get_json()["reason"] == "blocked"


def test_login_bad_credentials_returns_401(client, monkeypatch):
    def fake_login(email, password, session_path=None, **kw):
        raise loopnet_auth.LoopNetLoginError("rejected", reason="bad_credentials")

    monkeypatch.setattr(loopnet_auth, "login_with_credentials", fake_login)
    resp = client.post("/api/loopnet/login",
                       json={"email": "a@b.com", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.get_json()["reason"] == "bad_credentials"


def test_session_status_reports_credentials(client, monkeypatch, tmp_path):
    resp = client.get("/api/loopnet/session/status")
    data = resp.get_json()
    assert data["credentials_saved"] is False
    assert data["credentials_email"] is None

    (tmp_path / "creds.json").write_text(
        json.dumps({"email": "a@b.com", "password": "s"}))
    resp = client.get("/api/loopnet/session/status")
    data = resp.get_json()
    assert data["credentials_saved"] is True
    assert data["credentials_email"] == "a@b.com"


def test_save_and_load_credentials_roundtrip(tmp_path):
    path = tmp_path / "creds.json"
    loopnet_auth.save_credentials("a@b.com", "s3cret", credentials_path=path)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert loopnet_auth.load_credentials(path) == {"email": "a@b.com",
                                                   "password": "s3cret"}


def test_load_credentials_missing_or_invalid(tmp_path):
    assert loopnet_auth.load_credentials(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    assert loopnet_auth.load_credentials(bad) == {}
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"email": "a@b.com"}))
    assert loopnet_auth.load_credentials(incomplete) == {}


def test_build_session_reports_missing_expected():
    session = loopnet_auth._build_session({"SessionFarm_GUID": "g"})
    assert session["missing_expected"] == ["UserPreferences",
                                           "UserInfo_AssociateID"]
    assert session["cookie_string"] == "SessionFarm_GUID=g"

from pathlib import Path
from tempfile import TemporaryDirectory

from app.pipeline import find_highlights
from app.security import hash_password, verify_password


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("classroom-secret")
    second = hash_password("classroom-secret")
    assert first != second
    assert verify_password("classroom-secret", first)
    assert not verify_password("incorrect", first)


def test_highlights_are_built_from_transcript_segments():
    rows = [
        {"start": 0.0, "end": 8.0, "text": "First, let us understand why this function returns a value."},
        {"start": 8.2, "end": 17.0, "text": "Because we pass the input here, the output changes in this example."},
        {"start": 17.1, "end": 27.0, "text": "Remember this concept when you write your own code."},
    ]
    highlights = find_highlights(rows)
    assert highlights
    assert "function" in highlights[0]["transcript"]
    assert highlights[0]["start"] == 0.0
    assert highlights[0]["end"] == 17.0
    assert 0 <= highlights[0]["score"] <= 99


def test_local_account_registration_and_authentication(monkeypatch):
    import pytest
    from app import db
    from app.main import Credentials, login, register
    from app.security import current_user
    from fastapi import HTTPException
    from starlette.requests import Request

    with TemporaryDirectory(prefix=".test-db-", dir=Path(__file__).parent) as directory:
        monkeypatch.setattr(db, "DB_PATH", Path(directory) / "reel-studio-test.sqlite3")
        db.initialize()
        body = Credentials(email="teacher@example.com", password="classroom-secret")
        created = register(body)
        token = created["token"]
        request = Request({"type": "http", "headers": [(b"authorization", f"Bearer {token}".encode())]})
        assert current_user(request) == created["user"]["id"]
        assert login(body)["user"]["email"] == "teacher@example.com"
        with pytest.raises(HTTPException) as error:
            current_user(Request({"type": "http", "headers": []}))
        assert error.value.status_code == 401
        with pytest.raises(HTTPException) as duplicate:
            register(body)
        assert duplicate.value.status_code == 409


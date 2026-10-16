from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from app import db
from app.publishing import DurablePublisher, MockProvider, encrypt, decrypt, validate_schedule


def seed_job(db_path, platform="mock", state="scheduled", scheduled_at=None):
    db.DB_PATH = db_path
    db.initialize()
    timestamp = datetime.now(timezone.utc).isoformat()
    scheduled_at = scheduled_at or "2000-01-01T00:00:00+00:00"
    with db.connect() as conn:
        conn.execute("INSERT INTO users VALUES('u','u@example.com','hash',?)", (timestamp,))
        conn.execute("INSERT INTO videos(id,user_id,name,file_path,mime_type,size_bytes,status,created_at) VALUES('v','u','v.mp4',?,'video/mp4',1,'ready',?)", (str(db_path.parent / "video.mp4"),timestamp))
        conn.execute("INSERT INTO clips(id,video_id,title,start,end,score,transcript,created_at) VALUES('c','v','clip',0,10,80,'lesson',?)", (timestamp,))
        conn.execute("INSERT INTO exports(id,clip_id,video_id,file_path,status,created_at,width,height,duration) VALUES('e','c','v',?,'ready',?,1080,1920,10)", (str(db_path.parent / "video.mp4"),timestamp))
        conn.execute("INSERT INTO publishing_jobs(id,user_id,export_id,platform,title,caption,scheduled_at,timezone,state,confirmed_at,created_at,updated_at) VALUES('j','u','e',?,'lesson','',?,'UTC',?,?,?,?)", (platform,scheduled_at,state,timestamp,timestamp,timestamp))


def test_timezone_is_converted_to_utc_and_future_is_required():
    utc = validate_schedule("2030-06-01T18:30", "Asia/Kolkata")
    assert utc == datetime(2030, 6, 1, 13, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="future"):
        validate_schedule("2000-01-01T00:00", "UTC")


def test_invalid_timezone_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        validate_schedule("2030-06-01T18:30", "No/Such_Zone")


def test_credentials_are_encrypted_and_tampering_fails(monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("APP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    encrypted = encrypt({"refresh_token": "secret"})
    assert "secret" not in encrypted
    assert decrypt(encrypted)["refresh_token"] == "secret"
    with pytest.raises(Exception): decrypt(encrypted[:-4] + "xxxx")


def test_claim_is_transactional_and_does_not_duplicate_job(monkeypatch, tmp_path):
    path = tmp_path / "jobs.sqlite3"; seed_job(path)
    media = tmp_path / "video.mp4"; media.write_bytes(b"mock")
    worker = DurablePublisher(lambda *_: media)
    assert worker.claim_due()["id"] == "j"
    assert worker.claim_due() is None
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM publishing_jobs WHERE id='j'").fetchone()[0] == 1
        assert conn.execute("SELECT state FROM publishing_jobs WHERE id='j'").fetchone()[0] == "uploading"


def test_transient_mock_upload_is_retried_with_backoff(monkeypatch, tmp_path):
    path = tmp_path / "jobs.sqlite3"; seed_job(path)
    media = tmp_path / "video.mp4"; media.write_bytes(b"mock")
    monkeypatch.setenv("MOCK_PUBLISH_FAIL", "1")
    worker = DurablePublisher(lambda *_: media)
    assert worker.run_once()
    with db.connect() as conn:
        job = conn.execute("SELECT state,error,next_attempt_at,attempts FROM publishing_jobs WHERE id='j'").fetchone()
    assert job["state"] == "scheduled" and job["error"] and job["next_attempt_at"] and job["attempts"] == 1


def test_invalid_media_is_permanent_and_not_retried(monkeypatch, tmp_path):
    path = tmp_path / "jobs.sqlite3"; seed_job(path)
    worker = DurablePublisher(lambda *_: tmp_path / "missing.mp4")
    assert worker.run_once()
    with db.connect() as conn: job = conn.execute("SELECT state,error,next_attempt_at FROM publishing_jobs WHERE id='j'").fetchone()
    assert job["state"] == "failed" and job["error"] and job["next_attempt_at"] is None


def test_draft_requires_explicit_schedule_confirmation_and_persists(monkeypatch, tmp_path):
    path = tmp_path / "jobs.sqlite3"; seed_job(path, state="cancelled")
    media = tmp_path / "video.mp4"; media.write_bytes(b"fixture")
    from app import main
    from fastapi import HTTPException
    monkeypatch.setattr(main.publisher,"start",lambda:None)
    draft = main.create_publishing_draft(main.DraftPublishRequest(export_id="e",platform="mock",title="Lesson",caption="Description"),user_id="u")
    assert draft["state"] == "draft"
    with db.connect() as conn:
        assert conn.execute("SELECT state FROM publishing_jobs WHERE id=?",(draft["id"],)).fetchone()[0] == "draft"
    monkeypatch.setattr(main,"probe",lambda _path:{"width":1080,"height":1920,"duration":10,"has_audio":True})
    with pytest.raises(HTTPException) as err:
        main.schedule_publishing_draft(draft["id"],main.ScheduleDraftRequest(local_datetime="2035-01-01T12:00",timezone="UTC",confirm_publication=False,made_for_kids=False),user_id="u")
    assert err.value.status_code == 422
    future=(datetime.now(timezone.utc)+timedelta(minutes=8)).strftime("%Y-%m-%dT%H:%M")
    scheduled=main.schedule_publishing_draft(draft["id"],main.ScheduleDraftRequest(local_datetime=future,timezone="UTC",confirm_publication=True,made_for_kids=False,title="Updated lesson",caption="Edited"),user_id="u")
    assert scheduled["state"] == "scheduled"
    with db.connect() as conn:
        row=conn.execute("SELECT state,title,caption,self_declared_made_for_kids FROM publishing_jobs WHERE id=?",(draft["id"],)).fetchone()
    assert tuple(row)==("scheduled","Updated lesson","Edited",0)

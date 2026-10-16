"""Durable publishing queue, encrypted account tokens, and provider boundary."""
from __future__ import annotations

import base64
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import connect

STATES = {"draft", "scheduled", "uploading", "processing", "published", "failed", "cancelled"}


def utcnow() -> datetime: return datetime.now(timezone.utc)
def iso(value: datetime) -> str: return value.astimezone(timezone.utc).isoformat()


def validate_schedule(local_value: str, zone_name: str) -> datetime:
    try:
        zone = ZoneInfo(zone_name)
        local = datetime.fromisoformat(local_value)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Choose a valid date, time, and IANA timezone.") from exc
    if local.tzinfo:
        raise ValueError("Send the selected local date and time without an embedded offset; timezone is a separate field.")
    first = local.replace(tzinfo=zone, fold=0)
    second = local.replace(tzinfo=zone, fold=1)
    if first.utcoffset() != second.utcoffset(): raise ValueError("This local time occurs twice during a daylight-saving change. Choose an unambiguous time.")
    resolved = first.astimezone(timezone.utc)
    if resolved.astimezone(zone).replace(tzinfo=None) != local: raise ValueError("This local time does not exist because of a daylight-saving change. Choose another time.")
    if resolved <= utcnow() + timedelta(minutes=2): raise ValueError("Choose a publishing time at least two minutes in the future.")
    return resolved


def encrypt(value: dict) -> str:
    key = os.getenv("APP_ENCRYPTION_KEY", "")
    if not key: raise RuntimeError("Set APP_ENCRYPTION_KEY before connecting a publishing account.")
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode()).encrypt(json.dumps(value).encode()).decode()
    except Exception as exc: raise RuntimeError("APP_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def decrypt(value: str) -> dict:
    from cryptography.fernet import Fernet
    return json.loads(Fernet(os.environ["APP_ENCRYPTION_KEY"].encode()).decrypt(value.encode()))


class Provider(Protocol):
    mock: bool
    def submit(self, job: dict, media: Path, credentials: dict | None) -> str: ...


class MockProvider:
    mock = True
    def submit(self, job: dict, media: Path, credentials: dict | None = None) -> str:
        if not media.is_file(): raise ValueError("The rendered media file is missing.")
        if os.getenv("MOCK_PUBLISH_FAIL") == "1": raise TimeoutError("Mock transient upload failure.")
        return "mock-" + job["id"]


class YouTubeProvider:
    mock = False
    def submit(self, job: dict, media: Path, credentials: dict | None) -> str:
        if not credentials: raise PermissionError("YouTube OAuth is not connected.")
        publish_at = datetime.fromisoformat(job["scheduled_at"])
        if publish_at <= utcnow() + timedelta(minutes=5): raise ValueError("The YouTube publish time is too close or has passed. Create a new schedule with at least 30 minutes of lead time.")
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc: raise RuntimeError("Install backend/requirements-publishing.txt to enable YouTube.") from exc
        creds = Credentials.from_authorized_user_info(credentials, ["https://www.googleapis.com/auth/youtube.upload"])
        service = build("youtube", "v3", credentials=creds, cache_discovery=False)
        request = service.videos().insert(part="snippet,status", body={
            "snippet": {"title": job["title"], "description": job["caption"]},
            "status": {"privacyStatus": "private", "publishAt": job["scheduled_at"], "selfDeclaredMadeForKids": bool(job["self_declared_made_for_kids"])},
        }, media_body=MediaFileUpload(str(media), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024))
        response = None
        while response is None:
            # Google retries transient chunk responses on this same resumable session.
            _, response = request.next_chunk(num_retries=3)
        if not response or not response.get("id"): raise RuntimeError("YouTube did not return a video ID.")
        # Persist renewed credentials only when a later worker update returns them.
        return str(response["id"])

    def is_public(self, provider_id: str, credentials: dict | None) -> bool:
        if not credentials: raise PermissionError("YouTube OAuth is no longer connected.")
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_info(credentials, ["https://www.googleapis.com/auth/youtube.upload"])
        item = build("youtube", "v3", credentials=creds, cache_discovery=False).videos().list(part="status,processingDetails", id=provider_id).execute()
        if not item.get("items"): raise ValueError("YouTube no longer returns this scheduled video.")
        status = item["items"][0].get("status", {})
        if status.get("uploadStatus") in {"failed", "rejected", "deleted"}:
            raise ValueError("YouTube processing failed: " + str(status.get("failureReason") or status.get("rejectionReason") or status.get("uploadStatus")))
        return status.get("privacyStatus") == "public" and status.get("uploadStatus") == "processed"


class DurablePublisher:
    """Single-process poller with transactional SQLite claims; safe to restart and run once per DB."""
    def __init__(self, media_lookup): self.media_lookup = media_lookup; self.stop = threading.Event(); self.thread = None
    def start(self):
        if self.thread and self.thread.is_alive(): return
        self.stop.clear(); self.thread = threading.Thread(target=self.run, name="publishing-worker", daemon=True); self.thread.start()
    def close(self): self.stop.set()
    def claim_due(self):
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM publishing_jobs WHERE state='scheduled' AND (platform='youtube' OR scheduled_at<=?) AND (next_attempt_at IS NULL OR next_attempt_at<=?) AND (lease_until IS NULL OR lease_until<=?) ORDER BY scheduled_at LIMIT 1", (iso(utcnow()), iso(utcnow()), iso(utcnow()))).fetchone()
            if not row: return None
            lease = iso(utcnow() + timedelta(minutes=20))
            db.execute("UPDATE publishing_jobs SET state='uploading',lease_until=?,attempts=attempts+1,updated_at=? WHERE id=? AND state='scheduled'", (lease, iso(utcnow()), row["id"]))
            if db.total_changes < 1: return None
            return dict(row)
    def claim_processing(self):
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM publishing_jobs WHERE state='processing' AND platform='youtube' AND (next_attempt_at IS NULL OR next_attempt_at<=?) AND (lease_until IS NULL OR lease_until<=?) ORDER BY scheduled_at LIMIT 1", (iso(utcnow()), iso(utcnow()))).fetchone()
            if not row: return None
            db.execute("UPDATE publishing_jobs SET lease_until=?,updated_at=? WHERE id=? AND state='processing'", (iso(utcnow() + timedelta(minutes=2)), iso(utcnow()), row["id"]))
            return dict(row)
    def run_once(self):
        job = self.claim_due()
        if not job:
            job = self.claim_processing()
            if not job: return False
            try:
                with connect() as db: row = db.execute("SELECT credentials FROM publishing_accounts WHERE user_id=? AND platform='youtube'", (job["user_id"],)).fetchone()
                credentials = decrypt(row["credentials"]) if row else None
                public = YouTubeProvider().is_public(job["provider_id"], credentials)
                with connect() as db: db.execute("UPDATE publishing_jobs SET state=?,next_attempt_at=?,lease_until=NULL,updated_at=? WHERE id=?", ("published" if public else "processing", None if public else iso(utcnow()+timedelta(minutes=2)), iso(utcnow()), job["id"]))
            except ValueError as exc: self.fail(job, str(exc), retry=False)
            except Exception as exc:
                message = str(exc)[:1000]
                if any(part in message.lower() for part in ("invalid_grant", "invalid credentials", "unauthorized", "401", "403")):
                    self.fail(job, message, retry=False)
                else:
                    with connect() as db: db.execute("UPDATE publishing_jobs SET error=?,next_attempt_at=?,lease_until=NULL,updated_at=? WHERE id=?", (message, iso(utcnow()+timedelta(minutes=5)), iso(utcnow()), job["id"]))
            return True
        try:
            provider = MockProvider() if job["platform"] == "mock" else YouTubeProvider()
            media = self.media_lookup(job["export_id"], job["user_id"])
            credentials = None
            if not provider.mock:
                with connect() as db: account = db.execute("SELECT credentials FROM publishing_accounts WHERE user_id=? AND platform=?", (job["user_id"], "youtube")).fetchone()
                credentials = decrypt(account["credentials"]) if account else None
            provider_id = provider.submit(job, media, credentials)
            with connect() as db:
                db.execute("UPDATE publishing_jobs SET state=?,provider_id=?,error=NULL,lease_until=NULL,updated_at=?,is_mock=? WHERE id=?", ("published" if provider.mock else "processing", provider_id, iso(utcnow()), int(provider.mock), job["id"]))
        except PermissionError as exc:
            self.fail(job, str(exc), retry=False)
        except ValueError as exc:
            self.fail(job, str(exc), retry=False)
        except Exception as exc:
            message = str(exc)[:1000]
            permanent = any(part in message.lower() for part in ("invalid_grant", "invalid credentials", "unauthorized", "401", "403"))
            # Once an API upload begins, an ambiguous transport error is not replayed
            # as a new videos.insert request; that could create a duplicate. The
            # provider's resumable chunk retry above is safe within the same session.
            safe_retry = job["platform"] == "mock" and not permanent and job["attempts"] < 5
            self.fail(job, message, retry=safe_retry)
        return True
    def fail(self, job, message, retry):
        with connect() as db:
            attempts = int(job["attempts"] or 0) + 1
            next_time = iso(utcnow() + timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))) if retry else None
            db.execute("UPDATE publishing_jobs SET state=?,error=?,next_attempt_at=?,lease_until=NULL,updated_at=? WHERE id=?", ("scheduled" if retry else "failed", message, next_time, iso(utcnow()), job["id"]))
    def run(self):
        while not self.stop.is_set():
            try: self.run_once()
            except Exception: pass
            self.stop.wait(2)

"""Reel Studio AI local-first API."""
from __future__ import annotations

import os
import importlib.util
import shutil
import threading
import uuid
import json
import base64
import hmac
import hashlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field

load_dotenv()

from .db import DATA_DIR, connect, initialize
from .learning import rank_learning_moments
from .pipeline import new_id, probe, render_reel, transcribe
from .publishing import DurablePublisher, encrypt, iso, validate_schedule
from .security import current_user, hash_password, issue_token, verify_password

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
ALLOWED_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
executor = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("JOB_WORKERS", "1"))), thread_name_prefix="reel-job")
jobs_lock = threading.Lock()
publisher = DurablePublisher(lambda export_id, user_id: _publishing_media(export_id, user_id))

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    publisher.start()
    yield
    publisher.close()


app = FastAPI(title="Reel Studio AI API", version="0.2.0", description="Local-first educational video to vertical reel workflow.", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_dict(row):
    return dict(row) if row is not None else None


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class ClipUpdate(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)


class LearningRerankRequest(BaseModel):
    target_duration: float = Field(default=35, ge=8, le=180)
    weights: dict[str, float] | None = None


class RenderRequest(BaseModel):
    brand_name: str = Field(default="", max_length=48)
    accent_color: str = Field(default="#8b73ff", pattern=r"^#[0-9a-fA-F]{6}$")
    crop_x: float = Field(default=0.5, ge=0, le=1)
    crop_y: float = Field(default=0.5, ge=0, le=1)
    crop_mode: str = Field(default="smart", pattern="^(smart|center|blur|slide)$")
    caption_style: str = Field(default="classic", pattern="^(classic|bold|boxed)$")


class PublishRequest(BaseModel):
    export_id: str
    platform: str = Field(pattern="^(youtube|mock)$")
    title: str = Field(min_length=1, max_length=100)
    caption: str = Field(default="", max_length=5000)
    local_datetime: str
    timezone: str = Field(min_length=1, max_length=80)
    confirm_publication: bool
    made_for_kids: bool | None = None


class DraftPublishRequest(BaseModel):
    export_id: str
    platform: str = Field(pattern="^(youtube|mock)$")
    title: str = Field(min_length=1, max_length=100)
    caption: str = Field(default="", max_length=5000)


class ScheduleDraftRequest(BaseModel):
    local_datetime: str
    timezone: str = Field(min_length=1, max_length=80)
    confirm_publication: bool
    made_for_kids: bool | None
    title: str | None = Field(default=None, min_length=1, max_length=100)
    caption: str | None = Field(default=None, max_length=5000)


def _publishing_media(export_id: str, user_id: str) -> Path:
    with connect() as db:
        row = db.execute("SELECT e.file_path FROM exports e JOIN videos v ON v.id=e.video_id WHERE e.id=? AND v.user_id=? AND e.status='ready'", (export_id, user_id)).fetchone()
    if not row: raise ValueError("The selected export is not ready or is not owned by this account.")
    path = Path(row["file_path"])
    if not path.is_file(): raise ValueError("Rendered media is missing from local storage.")
    return path


def get_video(video_id: str, user_id: str):
    with connect() as db:
        row = db.execute("SELECT * FROM videos WHERE id=? AND user_id=?", (video_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "Project not found.")
    return row_dict(row)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "service": "reel-studio-ai", "transcription": importlib.util.find_spec("faster_whisper") is not None, "ffmpeg": shutil.which(os.getenv("FFMPEG_PATH", "ffmpeg")) is not None, "ffprobe": shutil.which(os.getenv("FFPROBE_PATH", "ffprobe")) is not None, "smart_reframe": importlib.util.find_spec("cv2") is not None, "youtube_oauth": bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET") and os.getenv("APP_ENCRYPTION_KEY"))}


@app.post("/api/auth/register", status_code=201, tags=["auth"])
def register(body: Credentials):
    user_id = new_id()
    try:
        with connect() as db:
            db.execute("INSERT INTO users(id,email,password_hash,created_at) VALUES(?,?,?,?)", (user_id, str(body.email).lower(), hash_password(body.password), now()))
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise HTTPException(409, "An account with this email already exists.")
        raise
    return {"token": issue_token(user_id), "user": {"id": user_id, "email": str(body.email).lower()}}


@app.post("/api/auth/login", tags=["auth"])
def login(body: Credentials):
    with connect() as db:
        user = db.execute("SELECT id,email,password_hash FROM users WHERE email=?", (str(body.email).lower(),)).fetchone()
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"token": issue_token(user["id"]), "user": {"id": user["id"], "email": user["email"]}}


@app.get("/api/auth/me", tags=["auth"])
def me(user_id: str = Depends(current_user)):
    with connect() as db:
        user = db.execute("SELECT id,email FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(401, "Account no longer exists.")
    return dict(user)


@app.post("/api/videos", status_code=201, tags=["videos"])
async def upload_video(request: Request, file: UploadFile = File(...), user_id: str = Depends(current_user)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(415, "Choose an MP4, MOV, M4V, WebM, or MKV video.")
    video_id = new_id()
    directory = DATA_DIR / "uploads" / user_id
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{video_id}{suffix}"
    size = 0
    try:
        with destination.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"Video exceeds the {MAX_UPLOAD_BYTES // 1024 // 1024} MB upload limit.")
                output.write(chunk)
        if size == 0:
            raise HTTPException(400, "The selected file is empty.")
        try:
            metadata = probe(destination)
        except RuntimeError as exc:
            raise HTTPException(422, str(exc)) from exc
        with connect() as db:
            db.execute("INSERT INTO videos(id,user_id,name,file_path,mime_type,size_bytes,duration,width,height,status,created_at,frame_rate,has_audio) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (video_id,user_id,Path(file.filename or "lesson").name,file_path(destination),file.content_type or "video/mp4",size,metadata["duration"],metadata["width"],metadata["height"],"uploaded",now(),metadata["frame_rate"],int(metadata["has_audio"])))
        return {"id": video_id, "name": Path(file.filename or "lesson").name, "status": "uploaded", **metadata, "size_bytes": size, "created_at": now()}
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def file_path(path: Path) -> str:
    return str(path.resolve())


@app.get("/api/videos", tags=["videos"])
def list_videos(user_id: str = Depends(current_user)):
    with connect() as db:
        rows = db.execute("""SELECT v.id,v.name,v.mime_type,v.size_bytes,v.duration,v.width,v.height,v.frame_rate,v.has_audio,v.status,v.created_at,v.error,
          (SELECT COUNT(*) FROM clips c WHERE c.video_id=v.id) clip_count,
          (SELECT COUNT(*) FROM exports e WHERE e.video_id=v.id AND e.status='ready') export_count,
          (SELECT j.stage FROM jobs j WHERE j.video_id=v.id ORDER BY j.created_at DESC LIMIT 1) stage
          FROM videos v WHERE v.user_id=? ORDER BY v.created_at DESC""", (user_id,)).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/videos/{video_id}", tags=["videos"])
def video_detail(video_id: str, user_id: str = Depends(current_user)):
    video = get_video(video_id, user_id)
    video.pop("file_path", None)
    with connect() as db:
        video["clips"] = [_clip_response(x) for x in db.execute("SELECT * FROM clips WHERE video_id=? ORDER BY score DESC", (video_id,))]
        video["exports"] = []
        for row in db.execute("SELECT e.id,e.status,e.created_at,e.duration,e.width,e.height,e.error,e.metadata_json,c.title clip_title FROM exports e JOIN clips c ON c.id=e.clip_id WHERE e.video_id=? ORDER BY e.created_at DESC", (video_id,)):
            item = dict(row); item["metadata"] = json.loads(item.pop("metadata_json")) if item.get("metadata_json") else None
            video["exports"].append(item)
        latest_job = db.execute("SELECT id,status,stage,progress,error FROM jobs WHERE video_id=? ORDER BY created_at DESC LIMIT 1", (video_id,)).fetchone()
        video["job"] = dict(latest_job) if latest_job else None
    return video


@app.get("/api/videos/{video_id}/source", tags=["videos"])
def source_video(video_id: str, user_id: str = Depends(current_user)):
    video = get_video(video_id, user_id)
    path = Path(video["file_path"])
    if not path.is_file():
        raise HTTPException(410, "The original video is missing from local storage.")
    return FileResponse(path, media_type=video["mime_type"], filename=video["name"])


def _clip_response(row):
    item = dict(row)
    item["source_video_id"] = item.get("video_id")
    for column, output in (("signals", "signals"), ("evidence_json", "evidence"),
                           ("score_breakdown_json", "score_breakdown"), ("warnings_json", "warnings")):
        try:
            item[output] = json.loads(item.pop(column))
        except (KeyError, TypeError, json.JSONDecodeError):
            item[output] = [] if output in {"signals", "evidence", "warnings"} else {}
    return item


@app.post("/api/videos/{video_id}/process", status_code=202, tags=["videos"])
def start_processing(video_id: str, user_id: str = Depends(current_user)):
    video = get_video(video_id, user_id)
    with jobs_lock:
        with connect() as db:
            active = db.execute("SELECT id FROM jobs WHERE video_id=? AND status IN ('queued','running')", (video_id,)).fetchone()
            if active:
                return {"job_id": active["id"], "status": "running"}
            job_id = new_id()
            db.execute("INSERT INTO jobs(id,video_id,status,stage,progress,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (job_id,video_id,"queued","queued",0,now(),now()))
            db.execute("UPDATE videos SET status='processing',error=NULL WHERE id=?", (video_id,))
        executor.submit(process_video, job_id, video)
    return {"job_id": job_id, "status": "queued"}


def set_job(job_id: str, status: str, stage: str, progress: int, error: str | None = None):
    with connect() as db:
        db.execute("UPDATE jobs SET status=?,stage=?,progress=?,error=?,updated_at=? WHERE id=?", (status,stage,progress,error,now(),job_id))


def process_video(job_id: str, video: dict):
    try:
        set_job(job_id,"running","transcribing",0)
        segments, language = transcribe(Path(video["file_path"]))
        with connect() as db:
            db.execute("DELETE FROM transcript_segments WHERE video_id=?", (video["id"],))
            db.executemany("INSERT INTO transcript_segments(video_id,start,end,text) VALUES(?,?,?,?)", [(video["id"],s["start"],s["end"],s["text"]) for s in segments])
        set_job(job_id,"running","finding_highlights",50)
        ideas = rank_learning_moments(segments, source_video_id=video["id"], video_duration=video.get("duration"))
        with connect() as db:
            db.execute("DELETE FROM clips WHERE video_id=? AND review_status='suggested' AND edited=0 AND id NOT IN (SELECT clip_id FROM exports)", (video["id"],))
            db.executemany("""INSERT INTO clips(id,video_id,title,start,end,score,transcript,created_at,moment_type,signals,quality_score,
              explanation,evidence_json,score_breakdown_json,warnings_json,review_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              [(new_id(),video["id"],x["title"],x["start"],x["end"],x["score"],x["transcript"],now(),x["moment_type"],json.dumps(x["signals"]),x["quality_score"],x["explanation"],json.dumps(x["evidence"]),json.dumps(x["score_breakdown"]),json.dumps(x["warnings"]),"suggested") for x in ideas])
            db.execute("UPDATE videos SET status='ready' WHERE id=?", (video["id"],))
        set_job(job_id,"succeeded","complete",100)
    except Exception as exc:
        message = str(exc)[:1000]
        with connect() as db:
            db.execute("UPDATE videos SET status='failed',error=? WHERE id=?", (message,video["id"]))
        set_job(job_id,"failed","failed",100,message)


@app.get("/api/jobs/{job_id}", tags=["jobs"])
def get_job(job_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT j.* FROM jobs j JOIN videos v ON v.id=j.video_id WHERE j.id=? AND v.user_id=?", (job_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,"Job not found.")
    return dict(row)


@app.get("/api/videos/{video_id}/clips", tags=["clips"])
def list_clips(video_id: str, user_id: str = Depends(current_user)):
    get_video(video_id,user_id)
    with connect() as db:
        return [_clip_response(x) for x in db.execute("SELECT * FROM clips WHERE video_id=? ORDER BY score DESC", (video_id,))]


@app.post("/api/videos/{video_id}/rerank", tags=["clips"])
def rerank_video(video_id: str, body: LearningRerankRequest, user_id: str = Depends(current_user)):
    video = get_video(video_id, user_id)
    with connect() as db:
        rows = [dict(row) for row in db.execute("SELECT start,end,text FROM transcript_segments WHERE video_id=? ORDER BY start", (video_id,))]
    if not rows:
        raise HTTPException(409, "This project has no transcript to rank yet. Run transcription first.")
    try:
        ideas = rank_learning_moments(rows, source_video_id=video_id, video_duration=video.get("duration"), target_duration=body.target_duration, weights=body.weights)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with connect() as db:
        # Retain approved, edited, or exported moments; replace only untouched suggestions.
        db.execute("DELETE FROM clips WHERE video_id=? AND review_status='suggested' AND edited=0 AND id NOT IN (SELECT clip_id FROM exports)", (video_id,))
        db.executemany("""INSERT INTO clips(id,video_id,title,start,end,score,transcript,created_at,moment_type,signals,quality_score,
          explanation,evidence_json,score_breakdown_json,warnings_json,review_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          [(new_id(),video_id,x["title"],x["start"],x["end"],x["score"],x["transcript"],now(),x["moment_type"],json.dumps(x["signals"]),x["quality_score"],x["explanation"],json.dumps(x["evidence"]),json.dumps(x["score_breakdown"]),json.dumps(x["warnings"]),"suggested") for x in ideas])
        result = [_clip_response(row) for row in db.execute("SELECT * FROM clips WHERE video_id=? ORDER BY score DESC", (video_id,))]
    return {"candidates": result, "count": len(ideas), "method": "normalized weighted heuristic"}


@app.patch("/api/clips/{clip_id}", tags=["clips"])
def update_clip(clip_id: str, body: ClipUpdate, user_id: str = Depends(current_user)):
    if body.end <= body.start:
        raise HTTPException(422,"Clip end must be after its start.")
    with connect() as db:
        row = db.execute("SELECT c.id,c.video_id,v.user_id,v.duration FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=? AND v.user_id=?", (clip_id,user_id)).fetchone()
        if not row:
            raise HTTPException(404,"Clip not found.")
        if body.end > row["duration"]:
            raise HTTPException(422,"Clip end cannot exceed the source video duration.")
        evidence = [dict(segment) for segment in db.execute("SELECT start,end,text FROM transcript_segments WHERE video_id=? AND end>? AND start<? ORDER BY start", (row["video_id"],body.start,body.end))]
        transcript = " ".join(segment["text"] for segment in evidence)
        warnings = ["Initial ranking score refers to the original suggestion boundaries; edited boundaries have not been rescored."]
        db.execute("UPDATE clips SET start=?,end=?,title=?,transcript=?,evidence_json=?,warnings_json=?,explanation='Teacher-edited boundaries; transcript evidence is updated to the selected range.',edited=1,review_status='suggested' WHERE id=?",
                   (body.start,body.end,body.title,transcript,json.dumps(evidence),json.dumps(warnings),clip_id))
        updated = db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
    return _clip_response(updated)


@app.post("/api/clips/{clip_id}/approve", tags=["clips"])
def approve_clip(clip_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT c.id FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=? AND v.user_id=?", (clip_id,user_id)).fetchone()
        if not row:
            raise HTTPException(404, "Clip not found.")
        db.execute("UPDATE clips SET review_status='approved' WHERE id=?", (clip_id,))
        return _clip_response(db.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone())


@app.post("/api/clips/{clip_id}/render", status_code=202, tags=["exports"])
def start_render(clip_id: str, body: RenderRequest, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT c.*,v.user_id,v.file_path FROM clips c JOIN videos v ON v.id=c.video_id WHERE c.id=? AND v.user_id=?", (clip_id,user_id)).fetchone()
        if not row:
            raise HTTPException(404,"Clip not found.")
        clip = dict(row)
        if clip["review_status"] != "approved":
            raise HTTPException(409, "Approve this learning moment before rendering.")
        export_id = new_id()
        target = DATA_DIR / "exports" / user_id / f"{export_id}.mp4"
        db.execute("INSERT INTO exports(id,clip_id,video_id,file_path,status,created_at) VALUES(?,?,?,?,?,?)", (export_id,clip_id,clip["video_id"],str(target.resolve()),"processing",now()))
    executor.submit(render_export,export_id,clip,target,body.model_dump())
    return {"id":export_id,"status":"processing","message":"Render queued. Check export history for the result."}


def render_export(export_id: str, clip: dict, target: Path, options: dict):
    try:
        with connect() as db:
            segments = [dict(x) for x in db.execute("SELECT start,end,text FROM transcript_segments WHERE video_id=? AND end>? AND start<? ORDER BY start", (clip["video_id"],clip["start"],clip["end"]))]
        metadata = render_reel(Path(clip["file_path"]),target,clip["start"],clip["end"],segments,options["brand_name"],options["accent_color"],options["crop_x"],options["crop_y"],options["crop_mode"],options["caption_style"])
        with connect() as db:
            db.execute("UPDATE exports SET status='ready',duration=?,width=?,height=?,metadata_json=?,error=NULL WHERE id=?", (metadata["duration"],metadata["width"],metadata["height"],json.dumps(metadata),export_id))
    except Exception as exc:
        target.unlink(missing_ok=True)
        with connect() as db:
            db.execute("UPDATE exports SET status='failed',error=? WHERE id=?", (str(exc)[:1000],export_id))


@app.get("/api/exports/{export_id}", tags=["exports"])
def get_export(export_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT e.id,e.status,e.created_at,e.duration,e.width,e.height,e.file_path,e.error,e.metadata_json,v.name video_name,c.title clip_title FROM exports e JOIN videos v ON v.id=e.video_id JOIN clips c ON c.id=e.clip_id WHERE e.id=? AND v.user_id=?", (export_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,"Export not found.")
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json")) if result.get("metadata_json") else None
    if result["status"] == "ready" and not Path(result["file_path"]).is_file():
        result["status"] = "missing"
    result["download_url"] = f"/api/exports/{export_id}/download" if result["status"] == "ready" else None
    result.pop("file_path",None)
    return result


@app.get("/api/publishing/status", tags=["publishing"])
def publishing_status(user_id: str = Depends(current_user)):
    with connect() as db:
        connected = db.execute("SELECT 1 FROM publishing_accounts WHERE user_id=? AND platform='youtube'", (user_id,)).fetchone() is not None
    configured = bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET") and os.getenv("APP_ENCRYPTION_KEY"))
    return {"youtube": {"configured": configured, "connected": connected}, "instagram": {"configured": False, "message": "Requires an eligible professional account and verified Meta permissions; not enabled."}, "mock": True}


def _oauth_state(user_id: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"user": user_id, "exp": int(datetime.now(timezone.utc).timestamp()) + 600}, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(os.getenv("APP_SECRET", "local-dev-only-change-this-secret").encode(), payload.encode(), hashlib.sha256).digest()
    return payload + "." + base64.urlsafe_b64encode(signature).decode().rstrip("=")


def _read_oauth_state(state: str) -> str:
    try:
        payload, signature = state.split(".", 1)
        expected = base64.urlsafe_b64encode(hmac.new(os.getenv("APP_SECRET", "local-dev-only-change-this-secret").encode(), payload.encode(), hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < datetime.now(timezone.utc).timestamp(): raise ValueError()
        return data["user"]
    except Exception as exc: raise HTTPException(400, "OAuth state is invalid or expired.") from exc


@app.post("/api/publishing/youtube/connect", tags=["publishing"])
def youtube_connect(user_id: str = Depends(current_user)):
    client_id, client_secret, redirect_uri = (os.getenv(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"))
    if not all((client_id, client_secret, redirect_uri, os.getenv("APP_ENCRYPTION_KEY"))):
        raise HTTPException(503, "YouTube publishing is not configured. Set the server-side Google OAuth values and encryption key.")
    try:
        from google_auth_oauthlib.flow import Flow
        flow = Flow.from_client_config({"web": {"client_id": client_id, "client_secret": client_secret, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [redirect_uri]}}, scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"])
        flow.redirect_uri = redirect_uri
        url, _ = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent", state=_oauth_state(user_id))
        return {"authorization_url": url}
    except ImportError as exc: raise HTTPException(503, "Install backend/requirements-publishing.txt to enable YouTube OAuth.") from exc


@app.get("/api/publishing/youtube/callback", include_in_schema=False)
def youtube_callback(state: str, code: str | None = None, error: str | None = None):
    if error or not code:
        return RedirectResponse(os.getenv("FRONTEND_URL", "http://localhost:3000") + "/publishing?error=youtube_oauth_cancelled")
    user_id = _read_oauth_state(state)
    try:
        from google_auth_oauthlib.flow import Flow
        redirect_uri = os.environ["GOOGLE_REDIRECT_URI"]
        flow = Flow.from_client_config({"web": {"client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"], "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": [redirect_uri]}}, scopes=["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"], state=state)
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        creds = flow.credentials
        secret = {"token": creds.token, "refresh_token": creds.refresh_token, "token_uri": creds.token_uri, "client_id": creds.client_id, "client_secret": creds.client_secret, "scopes": list(creds.scopes or [])}
        with connect() as db:
            previous = db.execute("SELECT credentials FROM publishing_accounts WHERE user_id=? AND platform='youtube'", (user_id,)).fetchone()
            if not secret["refresh_token"] and previous: secret["refresh_token"] = decrypt(previous["credentials"]).get("refresh_token")
            if not secret["refresh_token"]: raise RuntimeError("Google did not return an offline refresh token; reauthorize with consent.")
            db.execute("INSERT INTO publishing_accounts(user_id,platform,credentials,connected_at) VALUES(?,?,?,?) ON CONFLICT(user_id,platform) DO UPDATE SET credentials=excluded.credentials,connected_at=excluded.connected_at", (user_id,"youtube",encrypt(secret),now()))
        return RedirectResponse(os.getenv("FRONTEND_URL", "http://localhost:3000") + "/publishing?connected=youtube")
    except Exception:
        return RedirectResponse(os.getenv("FRONTEND_URL", "http://localhost:3000") + "/publishing?error=youtube_oauth")


@app.get("/api/publishing/jobs", tags=["publishing"])
def list_publishing_jobs(user_id: str = Depends(current_user)):
    with connect() as db:
        rows = db.execute("SELECT j.*,e.width,e.height,e.duration FROM publishing_jobs j JOIN exports e ON e.id=j.export_id WHERE j.user_id=? ORDER BY j.scheduled_at DESC", (user_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/publishing/jobs/drafts", status_code=201, tags=["publishing"])
def create_publishing_draft(body: DraftPublishRequest, user_id: str = Depends(current_user)):
    _publishing_media(body.export_id, user_id)
    job_id = new_id(); timestamp = now()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT id FROM publishing_jobs WHERE user_id=? AND export_id=? AND state IN ('draft','scheduled','uploading','processing','published')", (user_id,body.export_id)).fetchone()
        if exists: raise HTTPException(409, "This export already has an active or published job.")
        db.execute("INSERT INTO publishing_jobs(id,user_id,export_id,platform,title,caption,scheduled_at,timezone,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,'draft',?,?)", (job_id,user_id,body.export_id,body.platform,body.title.strip(),body.caption,"","UTC",timestamp,timestamp))
    return {"id": job_id, "state": "draft", "is_mock": body.platform == "mock"}


@app.post("/api/publishing/jobs/{job_id}/schedule", tags=["publishing"])
def schedule_publishing_draft(job_id: str, body: ScheduleDraftRequest, user_id: str = Depends(current_user)):
    if not body.confirm_publication: raise HTTPException(422, "Confirm the scheduled publication explicitly before scheduling this draft.")
    if body.made_for_kids is None: raise HTTPException(422, "Declare whether this content is made for kids before scheduling.")
    try: scheduled = validate_schedule(body.local_datetime, body.timezone)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT platform,export_id FROM publishing_jobs WHERE id=? AND user_id=? AND state='draft'", (job_id,user_id)).fetchone()
        if not row: raise HTTPException(404, "Draft not found or no longer editable.")
        media = _publishing_media(row["export_id"],user_id)
        metadata = probe(media)
        if (metadata["width"], metadata["height"]) != (1080,1920) or metadata["duration"] > 180: raise HTTPException(422,"This export no longer meets YouTube reel requirements.")
        if row["platform"] == "youtube":
            if scheduled <= datetime.now(timezone.utc)+timedelta(minutes=30): raise HTTPException(422,"Choose a YouTube publish time at least 30 minutes ahead.")
            if not db.execute("SELECT 1 FROM publishing_accounts WHERE user_id=? AND platform='youtube'", (user_id,)).fetchone(): raise HTTPException(503,"Connect a YouTube account before scheduling.")
        timestamp = now()
        db.execute("UPDATE publishing_jobs SET scheduled_at=?,timezone=?,state='scheduled',title=COALESCE(?,title),caption=COALESCE(?,caption),confirmed_at=?,self_declared_made_for_kids=?,error=NULL,updated_at=? WHERE id=? AND state='draft'", (iso(scheduled),body.timezone,body.title,body.caption,timestamp,int(body.made_for_kids),timestamp,job_id))
    publisher.start()
    return {"id":job_id,"state":"scheduled","scheduled_at":iso(scheduled),"timezone":body.timezone}


@app.post("/api/publishing/jobs", status_code=201, tags=["publishing"])
def create_publishing_job(body: PublishRequest, user_id: str = Depends(current_user)):
    if not body.confirm_publication: raise HTTPException(422, "Confirm the scheduled publication explicitly before saving this job.")
    if body.made_for_kids is None: raise HTTPException(422, "Declare whether this content is made for kids before scheduling.")
    try: scheduled = validate_schedule(body.local_datetime, body.timezone)
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    if body.platform == "youtube" and scheduled <= datetime.now(timezone.utc) + timedelta(minutes=30):
        raise HTTPException(422, "Choose a YouTube publish time at least 30 minutes ahead to allow the upload to finish while the video remains private.")
    media = _publishing_media(body.export_id, user_id)
    try: metadata = probe(media)
    except RuntimeError as exc: raise HTTPException(422, f"Rendered media validation failed: {exc}") from exc
    if (metadata["width"], metadata["height"]) != (1080, 1920): raise HTTPException(422, "Choose a validated 1080 × 1920 vertical export.")
    if metadata["duration"] > 180: raise HTTPException(422, "YouTube Shorts scheduling currently accepts reels up to 180 seconds.")
    if body.platform == "youtube":
        with connect() as db: connected = db.execute("SELECT 1 FROM publishing_accounts WHERE user_id=? AND platform='youtube'", (user_id,)).fetchone()
        if not connected: raise HTTPException(503, "Connect a YouTube account in Publishing settings before scheduling.")
    job_id = new_id(); timestamp = now(); state = "scheduled"
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT id FROM publishing_jobs WHERE user_id=? AND export_id=? AND state IN ('scheduled','uploading','processing','published')", (user_id,body.export_id)).fetchone()
        if exists: raise HTTPException(409, "This export already has an active or published job.")
        db.execute("INSERT INTO publishing_jobs(id,user_id,export_id,platform,title,caption,scheduled_at,timezone,state,confirmed_at,created_at,updated_at,self_declared_made_for_kids) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (job_id,user_id,body.export_id,body.platform,body.title.strip(),body.caption,iso(scheduled),body.timezone,state,timestamp,timestamp,timestamp,int(body.made_for_kids)))
    publisher.start()
    return {"id": job_id, "state": state, "scheduled_at": iso(scheduled), "timezone": body.timezone, "is_mock": body.platform == "mock"}


@app.post("/api/publishing/jobs/{job_id}/cancel", tags=["publishing"])
def cancel_publishing_job(job_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT state FROM publishing_jobs WHERE id=? AND user_id=?", (job_id,user_id)).fetchone()
        if not row: raise HTTPException(404, "Publishing job not found.")
        if row["state"] not in {"draft", "scheduled"}: raise HTTPException(409, "This job can no longer be cancelled safely after upload has started.")
        db.execute("UPDATE publishing_jobs SET state='cancelled',updated_at=? WHERE id=?", (now(),job_id))
    return {"id": job_id, "state": "cancelled"}


@app.post("/api/publishing/jobs/{job_id}/retry", tags=["publishing"])
def retry_publishing_job(job_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT state,provider_id,platform,attempts FROM publishing_jobs WHERE id=? AND user_id=?", (job_id,user_id)).fetchone()
        if not row: raise HTTPException(404, "Publishing job not found.")
        if row["state"] != "failed" or row["provider_id"] or (row["platform"] == "youtube" and row["attempts"] > 0): raise HTTPException(409, "Only mock failures or YouTube jobs that failed before upload began can be retried safely. Check YouTube Studio before creating another job after an upload error.")
        db.execute("UPDATE publishing_jobs SET state='scheduled',attempts=0,error=NULL,next_attempt_at=NULL,lease_until=NULL,updated_at=? WHERE id=?", (now(),job_id))
    publisher.start()
    return {"id": job_id, "state": "scheduled"}


@app.post("/api/exports/{export_id}/feedback", status_code=201, tags=["feedback"])
def add_feedback(export_id: str, body: dict, user_id: str = Depends(current_user)):
    rating = body.get("rating")
    if not isinstance(rating, int) or rating < 1 or rating > 5: raise HTTPException(422, "Rating must be an integer from 1 to 5.")
    with connect() as db:
        if not db.execute("SELECT 1 FROM exports e JOIN videos v ON v.id=e.video_id WHERE e.id=? AND v.user_id=?", (export_id,user_id)).fetchone(): raise HTTPException(404,"Export not found.")
        db.execute("INSERT INTO performance_feedback(id,user_id,export_id,rating,note,created_at) VALUES(?,?,?,?,?,?)", (new_id(),user_id,export_id,rating,str(body.get("note", ""))[:500],now()))
    return {"saved": True, "rating": rating}


@app.get("/api/exports/{export_id}/download", tags=["exports"])
def download_export(export_id: str, user_id: str = Depends(current_user)):
    with connect() as db:
        row = db.execute("SELECT e.file_path,e.status,c.title FROM exports e JOIN videos v ON v.id=e.video_id JOIN clips c ON c.id=e.clip_id WHERE e.id=? AND v.user_id=?", (export_id,user_id)).fetchone()
    if not row:
        raise HTTPException(404,"Export not found.")
    path = Path(row["file_path"])
    if row["status"] != "ready" or not path.is_file():
        raise HTTPException(410,"This rendered file is not available. It may have been removed from local storage.")
    return FileResponse(path,media_type="video/mp4",filename=f"{row['title']}.mp4")

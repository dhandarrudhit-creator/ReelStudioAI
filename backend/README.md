# Reel Studio AI — replacement backend

Local-first FastAPI backend for video upload, media metadata, transcription with optional local Whisper, transcript-based clip suggestions, editable clips, vertical rendering and export validation.

## Requirements
- Python 3.11 or newer
- FFmpeg and FFprobe installed and available on PATH
- For transcription: `pip install -r requirements-whisper.txt` (Whisper downloads a model the first time it runs)

## Run on Windows
1. Install FFmpeg from https://ffmpeg.org/download.html and ensure `ffmpeg -version` and `ffprobe -version` work in a new terminal.
2. Double-click `run.bat`.
3. Open http://127.0.0.1:8000/docs and http://127.0.0.1:8000/health.
4. For transcription, stop the server, activate `.venv`, run `pip install -r requirements-whisper.txt`, and restart.

## Run on macOS/Linux
```bash
./run.sh
```

## Frontend connection
Set the frontend's backend base URL to the deployed API URL (local default `http://localhost:8000`). If the frontend uses a Next.js proxy, configure that proxy to forward to the backend. Set `CORS_ORIGINS` to your exact frontend origin. API routes are available both with and without the `/api` prefix for compatibility.

**Important for GitHub:** pushing source code to GitHub does not run a Python backend. Deploy this backend separately to a Python-capable host or run it on your own machine. Configure the frontend's environment variable/proxy to the deployed backend URL. Do not commit `.env`, uploaded videos, database files, or secrets. SQLite and local media storage require a persistent disk; ephemeral serverless deployments will lose them.

## API flow
1. `POST /api/projects` multipart field `file` (optional `title`)
2. `POST /api/projects/{id}/transcribe`, poll `GET /api/jobs/{job_id}`
3. `POST /api/projects/{id}/analyze`, poll job
4. `GET /api/projects/{id}/clips`; edit with `PATCH /api/clips/{clip_id}`
5. `POST /api/clips/{clip_id}/render`, poll job
6. `GET /api/clips/{clip_id}/exports`; download with `GET /api/exports/{export_id}/download`

## Implemented endpoints
Health, local demo authentication, project upload/list/detail/delete, Range source streaming, transcription job, transcript retrieval, analysis job, clip CRUD, render jobs, export listing/download, job polling/SSE, presets. Series and social publishing endpoints explicitly return 501 until implemented/configured.

## Honest limitations
- The educational moment engine currently uses transcript keyword heuristics and fixed-length windows; it is not a trained semantic model.
- Whisper is optional and must be installed separately; CPU transcription can be slow.
- Caption burn-in, branding presets, cancellation, true token/session security, production-grade user isolation, and publishing integrations are not yet implemented.
- Local demo authentication is not production-ready. Add secure signed sessions and per-user resource authorization before public deployment.
- Browser integration must be checked against the exact current frontend source. The repository could not be cloned in the build environment, so this archive does not claim that every frontend endpoint/response contract has been verified.

## Tests
```bash
pip install -r requirements.txt
pip install pytest httpx
pytest -q
```

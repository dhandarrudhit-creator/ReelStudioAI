# Reel Studio AI

Reel Studio AI turns educational recordings into short vertical reels. The current local MVP includes account sign-in, persistent project history, video validation, local speech transcription, transcript-based highlight suggestions, manual clip trimming, subtitle rendering, institute watermarking, and MP4 export.

## What works in this MVP

- Register and sign in to a local account. Passwords are stored as salted PBKDF2 hashes. There is no email verification or password recovery in this local MVP.
- Upload MP4, MOV, M4V, WebM, or MKV videos up to 500 MB. FFprobe inspects actual media streams; the uploaded filename is never used as a storage path.
- Process speech with faster-whisper on the machine running the backend. Transcription is optional until the AI dependencies are installed.
- Review candidate moments built from the actual timestamped transcript using a documented heuristic. This is not a trained highlight model.
- Adjust the title and clip boundaries, choose a vertical crop focal point, add an institute name, then render a real 1080 × 1920 H.264 MP4 with captions through FFmpeg.
- Reopen saved projects and exports from the same local SQLite database and storage folder.

Logo image upload, speaker/screen tracking, WhisperX word alignment, and topic-to-explainer generation are not part of this first MVP.

Accounts and history are local to the computer running FastAPI. This MVP is not a hosted multi-tenant service: it does not provide email verification, password reset, account recovery, or a production session management system. Do not expose this local API directly to the public internet.

## Reframing and publishing additions

- FFprobe records the real frame rate and audio presence. FFmpeg outputs a validated 1080 × 1920 MP4 and can render face-guided smart crop (optional OpenCV, center fallback), adjustable center crop, blurred fill, or full-frame slide mode. Caption styles include classic, bold, and boxed.
- Candidate moments are transcript-derived and include heuristic educational moment types/signals and a Reel Quality Guard score. These are explainable heuristics, not a trained educational model or a guarantee of retention.
- Learning Moment Intelligence ranks transcript windows with normalized, configurable weights for definitions, Q&A, worked examples, summaries, completeness, boundaries, target duration, and overlap. Each candidate stores timestamped transcript evidence, an explanation, a per-feature breakdown, warnings, and review status. Reranking keeps approved, edited, or exported moments; edits reset approval and rendering requires explicit approval.
- Ranking accepts optional word timestamps and time-aligned scene/OCR evidence, but the current workflow does not produce PySceneDetect scenes or OCR samples. Without visual evidence, the visual-support weight is excluded from score normalization and the UI says it was not assessed.
- `/publishing` has a monthly calendar, queue, explicit publication confirmation, local mock provider, and optional YouTube OAuth. Jobs persist in SQLite and a backend poller claims work transactionally. Keep that backend running on persistent storage; there is no external always-on worker service bundled.
- YouTube API jobs upload as private and set YouTube's scheduled `publishAt`. The API project may require Google verification before public scheduling is allowed. Credentials are only accepted on the backend and encrypted in SQLite with `APP_ENCRYPTION_KEY`.
- Instagram remains unavailable until the account and Meta publishing permissions have been verified. Mock jobs are visibly marked and never publish publicly.
- A P3 feedback endpoint records per-export ratings for future analysis; no automatic model training or performance optimization is implemented yet.

### Optional dependencies

From `backend/`, install core requirements first, then as needed:

```powershell
python -m pip install -r requirements-video.txt       # OpenCV face tracking
python -m pip install -r requirements-publishing.txt  # YouTube OAuth/API and Fernet encryption
python -m pip install -r requirements-ai.txt          # local faster-whisper transcription
```

For YouTube, enable YouTube Data API v3 in a Google Cloud project, create a Web application OAuth client, add `http://127.0.0.1:8000/api/publishing/youtube/callback` as an authorized redirect URI, then set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, and `APP_ENCRYPTION_KEY` in `backend/.env`. Generate the key with:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Restart the backend, open Publishing, connect YouTube, choose a ready reel, set its local date/time and IANA timezone (for example `Asia/Kolkata`), and check the publication confirmation. The OAuth scope is upload plus read-only status polling. Refresh credentials are Fernet-encrypted in the local SQLite database. Never commit `.env` or `storage/`.

### Manual verification

1. Install FFmpeg/FFprobe and run the backend, frontend, and optional dependencies above.
2. Register, upload one landscape lesson with audio and one silent portrait video, process the transcript where speech exists, edit a clip, and render each crop mode. Confirm the editor reports 1080 × 1920 and use FFprobe on the downloaded MP4.
3. Try center/blur crop position sliders and caption styles; confirm the preview is a source-only live crop and the downloaded file is the completed FFmpeg render.
4. In Publishing, schedule a mock job for a future time, restart the backend, and verify the queue remains. For quick mock execution, set the job time just over two minutes ahead, then observe state; set `MOCK_PUBLISH_FAIL=1` to inspect retry/backoff, then turn it off.
5. Only connect a real channel after OAuth is configured. Schedule a test video in a private test channel and verify it remains private until YouTube's scheduled publish time. Do not test against an unintended public channel.

YouTube uploads consume API quota; Google currently documents `videos.insert` as a separately allocated upload method. OAuth review, account eligibility, API quota, and channel-level restrictions remain controlled by Google. A YouTube job left in `uploading` after a process crash is intentionally not auto-replayed, since `videos.insert` has no app-level idempotency key and blindly retrying could duplicate a public upload.

## Project layout

```text
ai-video-studio/
├── backend/
│   ├── app/
│   │   ├── main.py             # Auth and REST API, background job orchestration
│   │   ├── db.py               # SQLite schema and connections
│   │   ├── pipeline.py         # FFprobe, faster-whisper, highlights, FFmpeg render
│   │   └── security.py         # Local password hashing and signed bearer tokens
│   ├── tests/test_core.py      # Core password/highlight checks
│   ├── requirements.txt        # API and test dependencies
│   ├── requirements-ai.txt     # Optional local transcription dependency
│   └── .env.example
├── frontend/
│   ├── src/app/
│   │   ├── page.tsx            # Dashboard, project history, upload, exports, branding
│   │   ├── login/page.tsx      # Register and sign-in
│   │   ├── studio/[videoId]/page.tsx # Processing, highlights, editor, export history
│   │   ├── globals.css         # Responsive dark design system
│   │   └── layout.tsx
│   └── src/lib/                # Typed API client and domain types
├── docs/                       # Architecture, API, and deployment notes
└── storage/                    # Created at runtime; ignored by Git
```

## Prerequisites (Windows)

- Node.js 20.9 or newer and npm
- Python 3.10 or newer
- Git
- FFmpeg and FFprobe available in `PATH` ([FFmpeg downloads](https://ffmpeg.org/download.html))

Check the tools in PowerShell:

```powershell
node --version
npm --version
python --version
git --version
ffmpeg -version
ffprobe -version
```

## Run locally

### 1. Start the API

Open a PowerShell terminal in the repository and run:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and replace `APP_SECRET` with a long random value. For example, generate one with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Paste the generated value into `.env`. Then start the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API runs at <http://127.0.0.1:8000>. Interactive API docs are at <http://127.0.0.1:8000/docs>.

### 2. Enable local transcription

In a second terminal:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
```

Restart the API. The first transcription downloads the `base` model into `storage/models`; it needs network access and several hundred megabytes of disk, and first-run processing takes longer. The default configuration uses CPU `int8` quantization so a GPU is not required. Change `WHISPER_MODEL` to `tiny` for a smaller/faster but less accurate model. Audio quality, accents, Hinglish, and technical vocabulary affect accuracy.

If you skip this step, the app still starts and accounts/history work, but video processing returns an honest error asking you to install the optional dependency. It does not invent transcript or completion data.

### 3. Start the frontend

Open a third PowerShell terminal at the repository root:

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```

Open <http://localhost:3000>, create a local account, upload a short lesson, and open the project to inspect processing and suggested highlights. Keep the backend terminal running while a job or render is active; the MVP queue runs in the API process and is not durable across process restarts.

## Checks

```powershell
# Frontend, from frontend/
npm run lint
npx tsc --noEmit
npm run build

# Backend, from backend/
.\.venv\Scripts\python.exe -m pytest -q
```

The core tests cover password hashing and transcript highlight grouping. A real video integration check requires FFmpeg, the optional transcription model, and a short sample clip.

## Media notes

- Supported upload types are MP4, MOV, M4V, WebM, and MKV; actual decode validation is performed with FFprobe.
- Default upload limit is 500 MB and default duration limit is 60 minutes. Tune `MAX_UPLOAD_BYTES` and `MAX_MEDIA_SECONDS` in `backend/.env` if required.
- Processing runs in a single local worker by default. It is suitable for short development clips, not a high-availability job service.
- Subtitle timing is based on faster-whisper segment timestamps. Word-level forced alignment via WhisperX is not included in this first version.
- PySceneDetect and OpenCV are not required for the MVP. User-controlled center crop is implemented first; automated speaker/screen detection is a future enhancement.
- Video, SQLite metadata, and model files are stored under `storage/` by default and are excluded from Git.

## Environment variables

`backend/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `APP_SECRET` | local development placeholder | Signs local bearer tokens; replace before use |
| `DATA_DIR` | `../storage` | Uploads, exports, and local model storage |
| `DATABASE_PATH` | `<DATA_DIR>/reel-studio.sqlite3` | SQLite file location |
| `CORS_ORIGINS` | localhost ports 3000 | Explicit comma-separated frontend origins |
| `MAX_UPLOAD_BYTES` | `524288000` | Upload limit in bytes |
| `MAX_MEDIA_SECONDS` | `3600` | Maximum input duration |
| `WHISPER_MODEL` | `base` | faster-whisper model name |
| `FFMPEG_PATH` / `FFPROBE_PATH` | `ffmpeg` / `ffprobe` | Executable names or full paths |
| `JOB_WORKERS` | `1` | In-process background worker count |

`frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=/backend-api
API_PROXY_TARGET=http://127.0.0.1:8000
```

The browser sends API calls to the Next.js app on the same origin. Next.js then proxies `/backend-api/*` requests to FastAPI, which avoids browser CORS and `localhost` versus `127.0.0.1` differences. If FastAPI uses another address, change `API_PROXY_TARGET` and restart Next.js.

Never put tokens, passwords, or private keys in `NEXT_PUBLIC_*` variables. The browser stores the signed local access token in local storage; sign out to remove it.

## Deployment

The supported path today is local development. A free frontend host alone cannot run this pipeline: processing requires the FastAPI process, FFmpeg, local model files, writable storage, and sustained CPU time. Free serverless backends commonly time out or discard local files. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) before hosting anything, and keep a persistent local deployment until a suitable storage and job system is implemented.

## Open-source references

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — local transcription
- [WhisperX](https://github.com/m-bain/whisperX) — possible later word-level alignment
- [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) — possible later scene analysis
- [FFmpeg](https://github.com/FFmpeg/FFmpeg) — media extraction, subtitles, and rendering
- [OpenCV](https://github.com/opencv/opencv) — possible later frame analysis

Review the licenses of the software builds and codecs you distribute. FFmpeg build options affect its applicable license.

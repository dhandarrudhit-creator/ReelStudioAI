# API reference

Interactive request/response schemas are available at `http://127.0.0.1:8000/docs`. All endpoints except health and account registration/login require `Authorization: Bearer <token>`. JSON errors use FastAPI's `detail` field.

## Health and account

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | API, FFmpeg, and optional transcription availability |
| POST | `/api/auth/register` | Create a local account; JSON `{ "email": "...", "password": "at least 8 chars" }` |
| POST | `/api/auth/login` | Sign in; same JSON body as registration |
| GET | `/api/auth/me` | Return the current account |

Register and login return `{ "token": "...", "user": { "id": "...", "email": "..." } }`.

## Videos and processing

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/videos` | Multipart upload with field `file`; returns measured media metadata |
| GET | `/api/videos` | List this account's projects, statuses, highlight/export counts |
| GET | `/api/videos/{video_id}` | Project, latest job, clip candidates, and export history |
| GET | `/api/videos/{video_id}/source` | Stream the original upload for authorized preview |
| POST | `/api/videos/{video_id}/process` | Queue transcription and highlight detection; returns HTTP 202 and `job_id` |
| GET | `/api/jobs/{job_id}` | Read queue/running/succeeded/failed state and stage progress |
| GET | `/api/videos/{video_id}/clips` | List actual transcript-derived candidates |
| POST | `/api/videos/{video_id}/rerank` | Re-rank the saved transcript with optional `target_duration` (8–180 seconds) and a non-negative `weights` map |

The latest job is also included in project detail. Processing states include `queued`, `running`, `succeeded`, and `failed`; stages include `transcribing`, `finding_highlights`, `complete`, and `failed`.

## Clips and exports

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/api/clips/{clip_id}` | JSON `{ "start": 5.0, "end": 25.0, "title": "..." }` to adjust a clip |
| POST | `/api/clips/{clip_id}/approve` | Explicitly approve a reviewed candidate; title/boundary edits reset approval |
| POST | `/api/clips/{clip_id}/render` | Queue a render; optional JSON includes `brand_name`, hex `accent_color`, and crop coordinates `crop_x` / `crop_y` from 0 to 1 |
| GET | `/api/exports/{export_id}` | Poll queued render state and get a download URL when ready |
| GET | `/api/exports/{export_id}/download` | Download the actual MP4 when the file exists |

Render JSON also accepts `crop_mode` (`smart`, `center`, `blur`, `slide`) and `caption_style` (`classic`, `bold`, `boxed`). `smart` attempts optional OpenCV face sampling and truthfully falls back to center when no stable detection is found. Output is probed and must be 1080 × 1920 before it is marked ready. Export status includes detailed `error` text and the quality/reframe metadata.

Candidates include `source_video_id`, `explanation`, timestamped `evidence`, `warnings`, `review_status`, and `score_breakdown` (`features`, normalized `weights`, `weighted_points`, `assessed_features`, `total`, and method). Default weights are in `backend/app/learning.py`; the UI exposes weight sliders and target duration. If OCR/slide evidence is absent, `visual_support` is excluded from assessed weighted features rather than treated as zero-quality visual evidence. The ranking service accepts optional word timestamps, scene changes, and time-aligned visual evidence, but the current pipeline does not extract those signals.

## Scheduled publishing

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/publishing/status` | Report YouTube OAuth configuration and connection, mock availability, and Instagram gating |
| POST | `/api/publishing/youtube/connect` | Return a server-configured Google OAuth URL |
| GET | `/api/publishing/youtube/callback` | Complete OAuth and persist encrypted credentials |
| GET | `/api/publishing/jobs` | List account-owned queue/history |
| POST | `/api/publishing/jobs/drafts` | Save an export, target, title, and description without publishing |
| POST | `/api/publishing/jobs` | Schedule a ready export, chosen platform, title/caption, local date/time, IANA timezone, `made_for_kids`, and `confirm_publication: true` |
| POST | `/api/publishing/jobs/{id}/schedule` | Schedule an existing draft after explicit confirmation |
| POST | `/api/publishing/jobs/{id}/cancel` | Cancel only before upload starts |
| POST | `/api/publishing/jobs/{id}/retry` | Retry only failed jobs without a provider response ID |
| POST | `/api/exports/{id}/feedback` | Store a 1–5 rating and optional note for future performance analysis |

The publishing worker transactionally claims persisted SQLite jobs. YouTube is uploaded as private with a future API `status.publishAt`; YouTube schedules require a 30-minute lead and ask the user to declare the made-for-kids setting. Mock jobs are clearly marked and never contact social providers. Instagram is not enabled until eligibility is verified. See README for OAuth environment and manual setup.

An export in `processing` is not complete. `ready` indicates an output was probed after render. `missing`/HTTP 410 indicates the local file is no longer present. The export library is scoped to the signed-in account.

## Common status codes

- `201`: account or upload created.
- `202`: work queued; poll the returned job/export ID.
- `401`: sign in again.
- `404`: resource is missing or belongs to another account.
- `409`: duplicate account email.
- `413`: upload exceeds the configured size limit.
- `415`: unsupported video suffix.
- `422`: invalid fields, unreadable video, or duration outside limits.
- `410`: export file has been removed from local storage.

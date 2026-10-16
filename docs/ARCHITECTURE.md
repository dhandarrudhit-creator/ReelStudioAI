# Architecture

## Local-first system

The Next.js app runs in the browser and sends API calls to its same-origin `/backend-api` path. Next.js proxies those requests to FastAPI using the server-only `API_PROXY_TARGET` setting, avoiding browser CORS and loopback-host mismatches. FastAPI owns authentication, validation, media processing, SQLite persistence, and file downloads. Local SQLite and files under `storage/` are the source of truth.

```text
Browser / Next.js
  ├─ Local account and bearer token
  ├─ Upload and project/editor screens
  └─ Typed HTTP calls ──────────────┐
                                     ▼
FastAPI (localhost:8000) ─ SQLite (users, videos, jobs, clips, segments, exports, publishing)
  ├─ Upload staging → FFprobe validation
  ├─ In-process worker → faster-whisper → transcript heuristics
  ├─ Render worker → FFmpeg + FFprobe → validated MP4 in storage/exports
  └─ Durable SQLite publisher poller → mock or YouTube Data API
```

## Persistence

- `users`: email and salted password hash.
- `videos`: account owner, safe generated file path, original display name, measured media properties, and project state.
- `jobs`: current stage, progress, timestamps, and failure reason.
- `transcript_segments`: real ASR segment text with start/end timestamps.
- `clips`: editable candidate boundaries/title, review status, transcript evidence, explanation, warnings, and normalized weighted score components.
- `exports`: generated file path, lifecycle status, detailed failure, probed media, and quality metadata.
- `publishing_accounts`: backend-only Fernet-encrypted OAuth credentials.
- `publishing_jobs`: target, timezone-resolved UTC schedule, confirmation, state, retry, lease, and provider ID.
- `performance_feedback`: per-export ratings retained for future analysis; no model learns from them automatically.

Foreign keys are enabled on every connection. User-owned resources are looked up with both the resource ID and authenticated user ID. Video binaries are not stored in SQLite. `DATA_DIR` and `DATABASE_PATH` can be set separately.

## Processing lifecycle

1. Upload writes to a UUID filename in the account's upload folder. The original client filename is retained only for display and download naming.
2. FFprobe verifies that the file is decodable and includes a video stream. Size, suffix, and duration limits are checked.
3. `POST /api/videos/{id}/process` returns a job ID and schedules local work on a bounded thread pool.
4. faster-whisper transcribes the video audio. Transcript segments and timestamps are stored.
5. The educational ranking service groups transcript segments, calculates configurable feature scores, records supporting excerpts with source timestamps, and saves reviewable candidates. Scores are transparent rules, not model confidence. Optional word, scene, or OCR evidence is accepted by the service, but the current workflow only supplies transcript and video duration.
6. A teacher edits and explicitly approves a candidate. Boundary/title edits reset approval. `POST /api/clips/{id}/render` rejects unapproved moments, then queues FFmpeg. It trims, scales while preserving aspect ratio, applies a 9:16 crop, burns timed subtitles, and adds an optional institute watermark. FFprobe inspects the result before marking it ready.

Transcription and FFmpeg render work still uses a process-local thread pool and can be interrupted by a backend restart. Publishing jobs are durable in SQLite and transactionally claimed by a background poller. Ambiguous YouTube upload failures are not replayed automatically, because a new insert could duplicate the post. A public deployment still needs supervised workers, durable media storage, cleanup/retention policy, and hardened authentication.

## Authentication and trust boundaries

Passwords use PBKDF2-HMAC-SHA256 with a random salt. Bearer tokens are HMAC-signed, expire after 14 days, and use `APP_SECRET`. This is basic local account isolation; it is not a production identity provider. The browser stores its token in local storage. CORS is restricted to configured origins. The API should remain on loopback for this MVP.

Every FFmpeg invocation uses an argument array, not a shell command. User paths are not accepted as processing inputs. Upload size and duration limits are configurable. FFprobe must confirm exact 1080 × 1920 output before an export becomes ready. OAuth client secrets stay in server environment; account refresh tokens are encrypted in SQLite. Keep `APP_ENCRYPTION_KEY` backed up and outside Git; loss prevents reading saved OAuth tokens.

## Deliberate scope

Smart crop uses optional OpenCV face samples and falls back to center if detection is not stable. Slide mode preserves the full frame over a blurred backdrop. Learning-moment labels and quality scores are transcript heuristics, not an educational ML model. Instagram publishing is gated pending account eligibility/permission verification. Local storage and background processing require a continuously running backend; free serverless hosting is not assumed to support it.

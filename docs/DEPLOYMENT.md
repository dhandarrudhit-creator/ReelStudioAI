# Deployment notes

## Current supported deployment

Run the frontend and API on one trusted local computer. The local SQLite database, uploaded lessons, model weights, and rendered reels live on its disk. This mode is the tested development target.

## Why a free frontend-only host is insufficient

The application depends on a long-running Python API, FFmpeg/FFprobe, writable persistent storage, locally cached model weights, and CPU time that can exceed serverless request limits. A static frontend host does not provide these. Many free backend tiers sleep, have ephemeral filesystems, or time out during transcription/rendering. In those environments, history and media can disappear or processing can be terminated.

Do not point a public frontend to a laptop API exposed on the internet. The current local token scheme, account setup, and in-process job queue are intended for local development only.

## Before a public deployment

1. Replace the local account/token flow with a maintained authentication provider or hardened server-side sessions, including account recovery and rate limits.
2. Move long-running tasks into a durable queue with supervised workers and job cancellation/retry behavior.
3. Add persistent object storage, access controls, retention/deletion controls, backups, and data-protection guidance for recordings containing students.
4. Restrict API access, configure HTTPS and trusted origins, rotate signing keys, and add request/upload rate limits and observability.
5. Pin dependencies and verify the licenses of Python packages, FFmpeg build options/codecs, and model weights for the intended use.
6. Confirm the chosen host permits persistent CPU workers, enough memory/disk, and the expected processing time. A provider's free-tier limits can change; check its current terms before relying on it.

No paid service is required to run locally. The repository does not claim a zero-cost public deployment for the complete media pipeline.

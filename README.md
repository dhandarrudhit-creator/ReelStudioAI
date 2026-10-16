# AI Video Studio

AI Video Studio is a foundation for turning educational recordings into short videos and creating explainers from topic prompts. Phase 1 includes the web landing page, a small FastAPI health endpoint, and a connection indicator. AI processing, a database, authentication, and video rendering are planned for later phases.

## Project layout

~~~text
ai-video-studio/
├── frontend/                 # Next.js, React, TypeScript, and Tailwind CSS
│   ├── .env.example            # Frontend API address
│   └── src/app/               # Homepage, shared layout, and styles
├── backend/                  # FastAPI service
│   ├── app/main.py            # API app and health endpoint
│   ├── requirements.txt       # Python dependencies
│   └── .env.example           # Example backend settings
├── .gitignore
└── README.md
~~~

## Prerequisites on Windows

Install these tools before running the project:

- **Node.js LTS** (20.9 or newer) and npm: [nodejs.org](https://nodejs.org/en/download/)
- **Python** (3.10 or newer): [python.org/downloads](https://www.python.org/downloads/)
- **Git for Windows**: [git-scm.com](https://git-scm.com/download/win)
- **Visual Studio Code** (recommended): [code.visualstudio.com](https://code.visualstudio.com/)

PostgreSQL and FFmpeg are part of the planned stack, but Phase 1 does not use them yet. Install them when a later phase needs database or video processing features: [PostgreSQL for Windows](https://www.postgresql.org/download/windows/) and [FFmpeg downloads](https://ffmpeg.org/download.html) (the FFmpeg site links to Windows builds).

Open PowerShell in the project folder and check the required tools:

~~~powershell
node --version
npm --version
python --version
git --version
~~~

## Run the backend

Open a PowerShell terminal in the project folder and run:

~~~powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
~~~

The API runs at <http://127.0.0.1:8000>. Its interactive documentation is at <http://127.0.0.1:8000/docs>.

## Run the frontend

Open a **second** PowerShell terminal in the project folder and run:

~~~powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
~~~

Open <http://localhost:3000>. The homepage checks the backend and displays whether it is connected. Start the backend first; if it was stopped, use the retry button on the homepage after restarting it.

## Check the setup

- Visit <http://127.0.0.1:8000/api/health>. A working backend responds with a JSON status.
- Visit <http://localhost:3000>. The backend indicator should say **Backend connected** while the API is running.
- Stop the backend and retry the check. The indicator should change to **Backend offline**.

## Environment variables

Copy frontend/.env.example to frontend/.env.local and backend/.env.example to backend/.env for local development. These local files are ignored by Git. The example files contain only non-secret defaults; never put passwords, API keys, or other secrets in a committed file.

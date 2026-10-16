"use client";

import { useCallback, useEffect, useState } from "react";

type ConnectionState = "checking" | "connected" | "disconnected";

const apiBaseUrl = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

function SparkIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="m12 2 1.8 7.2L21 11l-7.2 1.8L12 20l-1.8-7.2L3 11l7.2-1.8L12 2Z" />
      <path d="m19 15 .9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" />
    </svg>
  );
}

function FilmIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="4" width="18" height="16" rx="3" />
      <path d="M7 4v16M17 4v16M3 9h4m-4 6h4m10-6h4m-4 6h4" />
    </svg>
  );
}

function CodeIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="m8 8-4 4 4 4m8-8 4 4-4 4m-3-10-2 12" />
    </svg>
  );
}

async function requestBackendStatus(signal?: AbortSignal): Promise<boolean> {
  try {
    const response = await fetch(apiBaseUrl + "/api/health", {
      cache: "no-store",
      signal: signal ?? AbortSignal.timeout(5000),
    });
    if (!response.ok) return false;
    const result: { status?: string } = await response.json();
    return result.status === "ok";
  } catch {
    return false;
  }
}

function BackendStatus() {
  const [state, setState] = useState<ConnectionState>("checking");

  const checkBackend = useCallback(async () => {
    setState("checking");
    const isConnected = await requestBackendStatus();
    setState(isConnected ? "connected" : "disconnected");
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void requestBackendStatus(controller.signal).then((isConnected) => {
      if (!controller.signal.aborted) {
        setState(isConnected ? "connected" : "disconnected");
      }
    });
    return () => controller.abort();
  }, []);

  const label = {
    checking: "Checking connection",
    connected: "Backend connected",
    disconnected: "Backend offline",
  }[state];

  return (
    <div className={"backend-status backend-status--" + state} aria-live="polite">
      <span className="status-dot" />
      <span>{label}</span>
      {state !== "checking" && (
        <button
          className="status-retry"
          onClick={() => void checkBackend()}
          type="button"
          aria-label="Check backend connection again"
        >
          Retry
        </button>
      )}
    </div>
  );
}

const workflowCards = [
  {
    number: "01",
    title: "Lecture to Shorts",
    description:
      "Find the clearest teaching moments in a class recording and shape them into ready-to-share vertical clips.",
    icon: FilmIcon,
    tags: ["Smart highlights", "Word-level captions"],
    className: "workflow-card--violet",
  },
  {
    number: "02",
    title: "Topic to Explainer",
    description:
      "Turn a topic into a concise lesson with a script, animated code, voiceover, and captions.",
    icon: CodeIcon,
    tags: ["AI-written script", "Animated code"],
    className: "workflow-card--peach",
  },
];

export default function Home() {
  return (
    <main className="studio-shell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="AI Video Studio home">
          <span className="brand-mark"><SparkIcon /></span>
          <span>AI Video <span className="brand-accent">Studio</span></span>
        </a>
        <div className="topbar-right">
          <span className="topbar-label">Your creative workspace</span>
          <BackendStatus />
        </div>
      </header>

      <section className="hero" id="top" aria-labelledby="hero-title">
        <div className="hero-copy">
          <div className="eyebrow"><span className="eyebrow-line" /> MADE FOR EDUCATORS</div>
          <h1 id="hero-title">Make every lesson<br /><span>a moment worth sharing.</span></h1>
          <p className="hero-description">
            Turn the best of your teaching into short videos students want to watch.
            Start with a class recording or bring a topic to life.
          </p>
          <a className="scroll-cue" href="#workflows">
            <span className="scroll-cue-icon">↓</span> Choose your starting point
          </a>
        </div>

        <div className="hero-art" aria-label="A preview of a vertical lesson video">
          <div className="art-orbit art-orbit--outer" />
          <div className="art-orbit art-orbit--inner" />
          <div className="art-spark art-spark--one">✳</div>
          <div className="art-spark art-spark--two">✦</div>
          <div className="preview-card">
            <div className="preview-topline"><span>LESSON PREVIEW</span><span className="preview-live"><i /> READY</span></div>
            <div className="preview-screen">
              <div className="screen-window">
                <div className="screen-window-bar"><i /><i /><i /><span>useEffect.tsx</span></div>
                <div className="code-lines" aria-hidden="true">
                  <span><b>1</b><em>useEffect</em>(() =&gt; {"{"}</span>
                  <span><b>2</b>  <strong>const</strong> data = fetchData();</span>
                  <span><b>3</b>  setResult(data);</span>
                  <span><b>4</b>{"}"}, []);</span>
                </div>
                <span className="cursor-dot" />
              </div>
              <div className="video-caption">Think of it as a side effect ✨</div>
              <div className="preview-watermark">LESSON<br />SNIPPET</div>
            </div>
            <div className="preview-controls"><span>▶</span><div className="preview-track"><i /></div><span>00:18</span><span className="preview-volume">◖</span></div>
          </div>
          <div className="floating-note"><span className="note-icon">✦</span><span><b>One clear idea.</b><small>Ready for your feed.</small></span></div>
        </div>
      </section>

      <section className="workflows" id="workflows" aria-labelledby="workflows-title">
        <div className="section-heading">
          <div>
            <div className="eyebrow"><span className="eyebrow-line" /> TWO WAYS TO CREATE</div>
            <h2 id="workflows-title">Where should we start?</h2>
          </div>
          <p>Pick a workflow. We’ll help you turn good teaching into great video.</p>
        </div>

        <div className="workflow-grid">
          {workflowCards.map((workflow) => {
            const Icon = workflow.icon;
            return (
              <article className={"workflow-card " + workflow.className} key={workflow.title}>
                <div className="card-top"><span className="card-number">{workflow.number} / WORKFLOW</span><span className="card-icon"><Icon /></span></div>
                <h3>{workflow.title}</h3>
                <p>{workflow.description}</p>
                <div className="card-bottom">
                  <div className="card-tags">{workflow.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
                  <span className="coming-soon">COMING SOON</span>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <footer className="footer">
        <span className="footer-brand"><span className="brand-mark brand-mark--small"><SparkIcon /></span> AI Video Studio</span>
        <span>Built for the next generation of learning.</span>
        <span className="footer-version">FOUNDATION · PHASE 1</span>
      </footer>
    </main>
  );
}

import type { Clip, Export, Job, User, VideoProject } from "./types";

// Requests go through Next.js so the browser only talks to its own origin.
// Configure the server-side API_PROXY_TARGET in next.config.ts when needed.
export const API_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "/backend-api").replace(/\/$/, "");
export const TOKEN_KEY = "reel-studio-token";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY);
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let response: Response;
  try { response = await fetch(API_URL + path, { ...init, headers, cache: "no-store" }); }
  catch { throw new ApiError("Could not reach the API through the local frontend. Keep the backend running at http://127.0.0.1:8000 and restart the frontend after changing its environment settings.", 0); }
  const responseText = await response.text();
  let payloadData: unknown = {};
  let payload: { detail?: unknown } = {};
  try {
    payloadData = responseText ? JSON.parse(responseText) : {};
    payload = payloadData as { detail?: unknown };
  }
  catch { /* Non-JSON proxy/server errors are reported with their HTTP status below. */ }
  if (!response.ok) {
    const detail = typeof payload.detail === "string"
      ? payload.detail
      : payload.detail === undefined ? "" : JSON.stringify(payload.detail);
    const message = detail || `API returned HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}. Check the backend terminal for its error details.`;
    throw new ApiError(message, response.status);
  }
  return payloadData as T;
}

export async function signIn(email: string, password: string, mode: "login" | "register") {
  const result = await api<{token:string;user:User}>(`/api/auth/${mode}`, { method:"POST", body:JSON.stringify({email,password}) });
  localStorage.setItem(TOKEN_KEY, result.token);
  return result.user;
}
export const getMe = () => api<User>("/api/auth/me");
export const getVideos = () => api<VideoProject[]>("/api/videos");
export const getVideo = (id: string) => api<VideoProject & {clips:Clip[];exports:Export[]}>(`/api/videos/${id}`);
export const getJob = (id: string) => api<Job>(`/api/jobs/${id}`);
export const getClips = (id: string) => api<Clip[]>(`/api/videos/${id}/clips`);
export const getExport = (id: string) => api<Export>(`/api/exports/${id}`);
export function formatTime(seconds: number) { const m=Math.floor(seconds/60), s=Math.floor(seconds%60); return `${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`; }

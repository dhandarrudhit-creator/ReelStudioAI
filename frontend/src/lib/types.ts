export type User = { id: string; email: string };
export type VideoProject = {
  id: string; name: string; status: "uploaded" | "processing" | "ready" | "failed";
  duration: number; width: number; height: number; frame_rate?: number|null; has_audio?: boolean|number; size_bytes: number; created_at: string;
  error?: string | null; clip_count: number; export_count: number; stage?: string | null;
};
export type Clip = { id: string; video_id: string; source_video_id?: string; title: string; start: number; end: number; score: number; transcript: string; moment_type?: string; signals?: string[]; quality_score?: number; explanation?: string; evidence?: {start:number;end:number;text:string;words?:{start:number;end:number;text:string}[]}[]; score_breakdown?: {features:Record<string,number>;weights:Record<string,number>;weighted_points:Record<string,number>;assessed_features:string[];total:number;method:string}; warnings?: string[]; review_status?: "suggested"|"approved"; edited?: number };
export type Export = { id: string; status: string; created_at: string; duration?: number; width?: number; height?: number; clip_title: string; video_name: string; error?: string|null; metadata?: {crop_mode?:string;crop_fallback?:string|null;quality_warnings?:string[];has_audio?:boolean}|null; download_url?: string | null };
export type Job = { id: string; status: string; stage: string; progress: number; error?: string | null };

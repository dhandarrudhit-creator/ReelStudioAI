"""Local media services. Heavy work runs in the job executor, never in request handlers."""
from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import Any

from .db import DATA_DIR, connect
from .learning import rank_learning_moments

FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_PATH", "ffprobe")
MAX_MEDIA_SECONDS = int(os.getenv("MAX_MEDIA_SECONDS", "3600"))


def run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg/FFprobe was not found. Install FFmpeg and add it to PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Media processing took too long and was stopped.") from exc
    if result.returncode:
        message = (result.stderr or "Media command failed")[-1800:]
        raise RuntimeError(message)
    return result


def probe(path: Path) -> dict[str, Any]:
    result = run([FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels", "-of", "json", str(path)], timeout=30)
    try:
        info = json.loads(result.stdout)
        fmt = info.get("format", {})
        video = next(s for s in info.get("streams", []) if s.get("codec_type") == "video")
        duration = float(fmt.get("duration", 0))
        if duration <= 0 or duration > MAX_MEDIA_SECONDS:
            raise RuntimeError(f"Video duration must be between 1 second and {MAX_MEDIA_SECONDS // 60} minutes.")
        def rate(value: str | None) -> float | None:
            if not value or value in {"0/0", "N/A"}: return None
            a, _, b = value.partition("/")
            try: return float(a) / float(b or 1)
            except (ValueError, ZeroDivisionError): return None
        frame_rate = rate(video.get("avg_frame_rate")) or rate(video.get("r_frame_rate"))
        return {"duration": duration, "width": int(video["width"]), "height": int(video["height"]), "frame_rate": frame_rate, "has_audio": any(s.get("codec_type") == "audio" for s in info.get("streams", []))}
    except (ValueError, KeyError, StopIteration, json.JSONDecodeError) as exc:
        raise RuntimeError("The uploaded file is not a readable video with a video stream.") from exc


def transcribe(path: Path) -> tuple[list[dict[str, Any]], str]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("Transcription is unavailable because faster-whisper is not installed. Install backend/requirements-ai.txt and restart the API.") from exc
    model = WhisperModel(os.getenv("WHISPER_MODEL", "base"), device="cpu", compute_type="int8", download_root=str(DATA_DIR / "models"))
    segments, info = model.transcribe(str(path), vad_filter=True)
    rows = [{"start": float(item.start), "end": float(item.end), "text": item.text.strip()} for item in segments if item.text.strip()]
    if not rows:
        raise RuntimeError("No speech was detected. Try a recording with clearer audio.")
    return rows, str(getattr(info, "language", "unknown"))


TEACHING_CUES = re.compile(r"\b(why|because|therefore|example|first|second|remember|means|concept|step|important|formula|code|function|class|result|so|अब|क्योंकि|उदाहरण|मतलब|ध्यान)\b", re.I)


MOMENT_CUES = {
    "concept_explanation": re.compile(r"\b(why|because|means|concept|principle|intuition|idea)\b", re.I),
    "worked_example": re.compile(r"\b(example|for instance|suppose|let us|step by step)\b", re.I),
    "code_demo": re.compile(r"\b(code|function|class|variable|program|output|debug)\b", re.I),
    "formula_or_result": re.compile(r"\b(formula|equation|therefore|result|solve|calculate|proof)\b", re.I),
    "check_understanding": re.compile(r"\b(remember|important|notice|question|think about|common mistake)\b", re.I),
}


def find_highlights(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Backward-compatible adapter used by transcription processing."""
    ranked = rank_learning_moments(rows)
    for candidate in ranked:
        candidate.pop("source_video_id", None)
    return ranked


def _smart_face_center(source: Path, start: float, end: float) -> tuple[float, float] | None:
    """Sample a few frames and estimate a stable face focal point; optional OpenCV dependency."""
    try:
        import cv2
    except ImportError:
        return None
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened(): return None
    classifier = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"))
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    centers = []
    try:
        for sec in [start + (end - start) * i / 8 for i in range(1, 8)]:
            capture.set(cv2.CAP_PROP_POS_MSEC, sec * 1000)
            ok, frame = capture.read()
            if not ok: continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = classifier.detectMultiScale(gray, scaleFactor=1.12, minNeighbors=5, minSize=(40, 40))
            if len(faces):
                x, y, w, h = max(faces, key=lambda item: item[2] * item[3])
                centers.append(((x + w / 2) / frame.shape[1], (y + h / 2) / frame.shape[0]))
    finally:
        capture.release()
    if len(centers) < 3: return None
    return (sum(p[0] for p in centers) / len(centers), sum(p[1] for p in centers) / len(centers))


def render_reel(source: Path, destination: Path, start: float, end: float, segments: list[dict[str, Any]], brand: str, accent: str, crop_x: float, crop_y: float, crop_mode: str = "center", caption_style: str = "classic", width: int = 1080, height: int = 1920) -> dict[str, Any]:
    requested_crop_mode = crop_mode
    if crop_mode not in {"smart", "center", "blur", "slide"}: raise RuntimeError("Unknown crop mode.")
    if caption_style not in {"classic", "bold", "boxed"}: raise RuntimeError("Unknown caption style.")
    if width != 1080 or height != 1920: raise RuntimeError("The current export profile is fixed at 1080 × 1920.")
    info = probe(source)
    if crop_mode == "smart":
        center = _smart_face_center(source, start, end)
        if center: crop_x, crop_y = center
        else: crop_mode = "center"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subtitles = destination.with_suffix(".srt")
    def stamp(sec: float) -> str:
        milliseconds = max(0, round(sec * 1000))
        hours, rem = divmod(milliseconds, 3_600_000)
        minutes, rem = divmod(rem, 60_000)
        seconds, millis = divmod(rem, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"
    selected = [s for s in segments if s["end"] > start and s["start"] < end]
    lines = []
    for index, segment in enumerate(selected, 1):
        line_start = max(0, segment["start"] - start)
        line_end = min(end - start, segment["end"] - start)
        lines.extend([str(index), f"{stamp(line_start)} --> {stamp(line_end)}", segment["text"].replace("\n", " "), ""])
    subtitles.write_text("\n".join(lines), encoding="utf-8")
    cx, cy = min(1.0, max(0.0, crop_x)), min(1.0, max(0.0, crop_y))
    subtitle_path = subtitles.as_posix().replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    styles = {"classic": "FontSize=20,BorderStyle=1,Outline=2", "bold": "FontSize=24,Bold=1,BorderStyle=1,Outline=3", "boxed": "FontSize=20,Bold=1,BorderStyle=3,Outline=1,BackColour=&HCC000000"}
    subtitle_filter = f"subtitles='{subtitle_path}':force_style='FontName=Arial,{styles[caption_style]},PrimaryColour=&H00FFFFFF,OutlineColour=&HBB000000,Alignment=2,MarginV=125'"
    # Slides fit intact over a blurred duplicate. Blur mode uses a center crop over that background.
    if crop_mode == "slide":
        vf = "split[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:8[blur];[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fit];[blur][fit]overlay=(W-w)/2:(H-h)/2"
    elif crop_mode == "blur":
        vf = f"split[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:8[blur];[fg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:x=(in_w-1080)*{cx:.4f}:y=(in_h-1920)*{cy:.4f}[fill];[blur][fill]overlay"
    else:
        vf = f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:x=(in_w-1080)*{cx:.4f}:y=(in_h-1920)*{cy:.4f},setsar=1"
    vf += f",{subtitle_filter}"
    if brand.strip():
        safe = brand.strip()[:48]
        for char in ("\\", ":", "'", "%", ",", "[", "]"):
            safe = safe.replace(char, "\\" + char)
        vf += f",drawtext=text='{safe}':fontcolor=0x{accent.lstrip('#')}:fontsize=38:box=1:boxcolor=black@0.50:boxborderw=18:x=(w-text_w)/2:y=h-180"
    try:
        run([FFMPEG, "-y", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{end-start:.3f}", "-vf", vf, "-map", "0:v:0", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(destination)], timeout=1800)
        output = probe(destination)
        if (output["width"], output["height"]) != (width, height): raise RuntimeError(f"FFmpeg output validation failed: expected {width}×{height}, got {output['width']}×{output['height']}.")
        output["source_has_audio"] = info["has_audio"]
        output["crop_mode"] = crop_mode
        output["crop_fallback"] = "center: no reliable face detections" if requested_crop_mode == "smart" and crop_mode == "center" else None
        output["resolution"] = "1080x1920"
        output["quality_warnings"] = ([] if output["has_audio"] else ["The source has no audio track."]) + (["No captions were available for this clip."] if not selected else [])
        return output
    finally:
        subtitles.unlink(missing_ok=True)


def new_id() -> str:
    return uuid.uuid4().hex

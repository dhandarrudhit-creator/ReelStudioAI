"""Interpretable transcript-based ranking for educational moments.

This is a rule-based review aid, not a trained educational-quality model. Scores
are weighted cue indicators and should always be reviewed by a teacher.
"""
from __future__ import annotations

import re
import math
from typing import Any

DEFAULT_WEIGHTS = {
    "definition": 1.0,
    "question_answer": 1.2,
    "worked_example": 1.4,
    "summary": 0.7,
    "completeness": 1.2,
    "visual_support": 0.4,
    "boundaries": 1.0,
    "duration_fit": 0.8,
    "redundancy": 0.8,
}

PATTERNS = {
    "definition": re.compile(r"\b(defined as|definition|means|refers to|is called|concept|principle)\b|का अर्थ|मतलब|परिभाषा", re.I),
    "question": re.compile(r"\?|\b(why|what|how|when|which|क्यों|क्या|कैसे)\b", re.I),
    "answer": re.compile(r"\b(because|therefore|so|the answer|this is why|since)\b|क्योंकि|इसलिए|उत्तर", re.I),
    "worked_example": re.compile(r"\b(example|for instance|suppose|let us|step by step|first|then|finally|calculate|solve)\b|उदाहरण|मान लीजिए|पहले|फिर|अंत में", re.I),
    "summary": re.compile(r"\b(in summary|to summarize|in conclusion|key takeaway|remember|the main idea|overall)\b|सारांश|याद रखें|मुख्य बात", re.I),
    "closure": re.compile(r"[.!?।]$|\b(therefore|thus|in summary|that is why|so we get|hence)\b$", re.I),
}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, round(value, 1)))


def _valid_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for row in rows:
        try:
            start, end, text = float(row["start"]), float(row["end"]), str(row["text"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if start >= 0 and end > start and text:
            valid.append({**row, "start": start, "end": end, "text": text})
    return sorted(valid, key=lambda row: (row["start"], row["end"]))


def _evidence(rows: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    excerpts = []
    for row in rows:
        if row["end"] <= start or row["start"] >= end:
            continue
        excerpt = {"start": row["start"], "end": row["end"], "text": row["text"]}
        if row.get("words"):
            excerpt["words"] = row["words"]
        excerpts.append(excerpt)
    return excerpts


def _title(text: str) -> str:
    cleaned = re.sub(r"^(so|now|okay|well|तो|अब|अच्छा)[,\s]+", "", text.strip(), flags=re.I)
    sentence = re.split(r"(?<=[.!?।])\s+", cleaned, maxsplit=1)[0]
    words = sentence.split()
    title = " ".join(words[:9]).strip(" ,.:;!?।")
    return (title[:72].rstrip() or "Learning moment")


def rank_learning_moments(
    rows: list[dict[str, Any]], *, source_video_id: str = "", video_duration: float | None = None,
    scene_changes: list[float] | None = None, visual_evidence: list[dict[str, Any]] | None = None,
    target_duration: float = 35.0, weights: dict[str, float] | None = None, limit: int = 8,
) -> list[dict[str, Any]]:
    """Rank actual transcript windows; optional scene/OCR evidence is time-aligned."""
    if not math.isfinite(target_duration) or target_duration <= 0:
        raise ValueError("Target duration must be a finite positive number.")
    if video_duration is not None and (not math.isfinite(video_duration) or video_duration <= 0):
        raise ValueError("Video duration must be a finite positive number.")
    rows = _valid_rows(rows)
    if video_duration is not None:
        rows = [row for row in rows if row["start"] < video_duration and row["end"] <= video_duration]
    weight_map = dict(DEFAULT_WEIGHTS)
    if weights:
        unknown = set(weights) - set(weight_map)
        if unknown:
            raise ValueError(f"Unknown score weights: {', '.join(sorted(unknown))}.")
        if any(not math.isfinite(value) or value < 0 for value in weights.values()) or not any(weights.get(key, default) > 0 for key, default in DEFAULT_WEIGHTS.items()):
            raise ValueError("Score weights must be non-negative and at least one must be positive.")
        weight_map.update(weights)

    # Form short, sentence-aware transcript windows; break long lectures into overlapping groups.
    groups: list[list[dict[str, Any]]] = []
    group: list[dict[str, Any]] = []
    for row in rows:
        if group and (row["start"] - group[0]["start"] > 48 or row["end"] - group[0]["start"] > 62):
            groups.append(group)
            group = []
        group.append(row)
        if row["text"].rstrip().endswith((".", "?", "!", "।")) and row["end"] - group[0]["start"] >= 16:
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    # Short or unpunctuated transcripts still yield evidence-backed review candidates.
    if not groups and rows:
        groups = [rows]

    scenes = sorted(float(x) for x in (scene_changes or []) if isinstance(x, (int, float)) and x >= 0)
    visuals = visual_evidence or []
    candidates = []
    stopwords = {"this", "that", "with", "from", "then", "your", "have", "will", "when", "what", "which", "into", "because", "there", "their", "they", "them", "are", "was", "were", "been", "about", "also", "here", "for", "and", "the", "you", "can", "our", "not"}
    for chunk in groups:
        start, end = chunk[0]["start"], chunk[-1]["end"]
        first_words = chunk[0].get("words") or []
        last_words = chunk[-1].get("words") or []
        if first_words:
            try:
                word_start = float(first_words[0]["start"])
                if chunk[0]["start"] <= word_start <= chunk[0]["end"]:
                    start = word_start
            except (KeyError, TypeError, ValueError):
                pass
        if last_words:
            try:
                word_end = float(last_words[-1]["end"])
                if chunk[-1]["start"] <= word_end <= chunk[-1]["end"]:
                    end = word_end
            except (KeyError, TypeError, ValueError):
                pass
        duration = end - start
        text = " ".join(row["text"] for row in chunk).strip()
        if duration < 8 or len(text) < 35:
            continue
        lower_text = text.lower()
        is_question = bool(PATTERNS["question"].search(text))
        has_answer = bool(PATTERNS["answer"].search(text))
        definition = 100 if PATTERNS["definition"].search(text) else 0
        qa = 100 if is_question and has_answer else 55 if is_question else 0
        example = 100 if PATTERNS["worked_example"].search(text) else 0
        summary = 100 if PATTERNS["summary"].search(text) else 0
        completeness = 100 if PATTERNS["closure"].search(text) else 55
        # A small transcript window relative to the requested duration scores better.
        duration_fit = _clamp(100 - abs(duration - target_duration) * 2.4)
        start_aligned = any(abs(start - scene) <= 1.5 for scene in scenes)
        end_aligned = any(abs(end - scene) <= 1.5 for scene in scenes)
        boundary = _clamp(65 + (17 if start_aligned else 0) + (18 if end_aligned else 0))
        visual_matches = [item for item in visuals if float(item.get("end", item.get("start", -1))) >= start and float(item.get("start", -1)) <= end and str(item.get("text", "")).strip()]
        visual_support = 100 if visual_matches else 0
        assessed = list(DEFAULT_WEIGHTS)
        if not visuals:
            assessed.remove("visual_support")
        opening = chunk[0]["text"].strip().lower()
        start_warning = opening.startswith(("because ", "and then ", "which means ", "so that ", "it is because ", "क्योंकि ", "और फिर "))
        end_warning = not bool(chunk[-1].get("words")) and not PATTERNS["closure"].search(chunk[-1]["text"])
        components = {"definition": definition, "question_answer": qa, "worked_example": example, "summary": summary,
                      "completeness": completeness, "visual_support": visual_support, "boundaries": boundary,
                      "duration_fit": duration_fit, "redundancy": 100}
        evidence = _evidence(rows, start, end)
        title = _title(text)
        terms = {token for token in re.findall(r"[\w]+", text.lower()) if len(token) > 3 and token not in stopwords}
        cues = [name for name, score in (("definition", definition), ("question_answer", qa), ("worked_example", example), ("summary", summary)) if score]
        explanation = "Selected for " + (", ".join(cues) if cues else "a complete transcript passage") + "; the score is based on visible rule signals below."
        warnings = []
        if start_warning: warnings.append("Start may lack context; word-level alignment is unavailable for this transcript segment.")
        if end_warning: warnings.append("The ending may cut off an explanation; review the last sentence and adjust the boundary.")
        if not visuals: warnings.append("No sampled slide or OCR evidence is available; visual support was not assessed.")
        candidates.append({"source_video_id": source_video_id, "start": start, "end": end, "title": title,
                           "transcript": text, "moment_type": cues[0] if cues else "lesson_summary", "signals": cues,
                           "explanation": explanation, "evidence": evidence, "score_breakdown": components,
                           "warnings": warnings, "review_status": "suggested", "quality_score": _clamp(completeness), "_assessed": assessed,
                           "_weights": weight_map, "_visual_matches": visual_matches, "_terms": terms})

    # Penalize near-duplicates using actual temporal overlap, independent of list ordering.
    candidates.sort(key=lambda item: (-sum(item["score_breakdown"][key] * candidates[0]["_weights"][key] for key in candidates[0]["_weights"]) if candidates else 0, item["start"]))
    selected: list[dict[str, Any]] = []
    for candidate in candidates:
        def is_redundant(old: dict[str, Any]) -> bool:
            temporal_overlap = min(old["end"], candidate["end"]) - max(old["start"], candidate["start"])
            time_duplicate = temporal_overlap > min(old["end"]-old["start"], candidate["end"]-candidate["start"]) * .55
            old_terms, new_terms = old.get("_terms", set()), candidate.get("_terms", set())
            similarity = len(old_terms & new_terms) / len(old_terms | new_terms) if old_terms and new_terms else 0
            return time_duplicate or similarity >= .65
        overlaps = [old for old in selected if is_redundant(old)]
        if overlaps:
            candidate["score_breakdown"]["redundancy"] = 0
            candidate["warnings"].append("This moment substantially overlaps a higher-ranked candidate.")
        weights_for_candidate = candidate.pop("_weights")
        visuals_for_candidate = candidate.pop("_visual_matches")
        assessed = candidate.pop("_assessed")
        total_weight = sum(weights_for_candidate[key] for key in assessed) or 1
        contributions = {key: round(candidate["score_breakdown"][key] * weights_for_candidate[key] / total_weight, 1) for key in assessed}
        candidate["score_breakdown"] = {"features": candidate["score_breakdown"], "weights": weights_for_candidate, "weighted_points": contributions,
                                         "assessed_features": assessed, "total": _clamp(sum(contributions.values())), "method": "normalized weighted heuristic"}
        candidate["score"] = candidate["score_breakdown"]["total"]
        if visuals_for_candidate:
            candidate["explanation"] += " Time-aligned OCR/slide text is present."
        selected.append(candidate)
    selected.sort(key=lambda item: (-item["score"], item["start"]))
    for candidate in selected:
        candidate.pop("_terms", None)
    return selected[:max(1, min(limit, 20))]

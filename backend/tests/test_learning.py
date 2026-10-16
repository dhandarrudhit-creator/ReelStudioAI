import pytest

from app.learning import DEFAULT_WEIGHTS, rank_learning_moments


def transcript():
    return [
        {"start": 10, "end": 18, "text": "What is a variable? A variable stores a value because the program needs to reuse it."},
        {"start": 18, "end": 25, "text": "For example, first assign a number, then use it in the next calculation."},
        {"start": 25, "end": 30, "text": "In summary, the variable keeps that value for later."},
    ]


def test_candidates_include_timestamped_evidence_and_transparent_scores():
    result = rank_learning_moments(transcript(), source_video_id="video-1", video_duration=60)
    assert result
    candidate = result[0]
    assert candidate["source_video_id"] == "video-1"
    assert candidate["start"] == 10
    assert candidate["end"] == 30
    assert candidate["evidence"][0]["start"] == 10
    assert candidate["evidence"][0]["text"].startswith("What is a variable")
    assert candidate["score_breakdown"]["method"] == "normalized weighted heuristic"
    assert candidate["score"] == candidate["score_breakdown"]["total"]
    assert "visual_support" not in candidate["score_breakdown"]["weighted_points"]
    assert any("No sampled slide" in warning for warning in candidate["warnings"])
    assert set(DEFAULT_WEIGHTS) == set(candidate["score_breakdown"]["weights"])


def test_configured_weights_are_normalized_and_unsupported_weights_rejected():
    result = rank_learning_moments(transcript(), weights={"worked_example": 8, "definition": 0})
    breakdown = result[0]["score_breakdown"]
    assert breakdown["weights"]["worked_example"] == 8
    assert sum(breakdown["weighted_points"].values()) == pytest.approx(breakdown["total"], abs=0.2)
    with pytest.raises(ValueError, match="Unknown score weights"):
        rank_learning_moments(transcript(), weights={"volume": 1})
    with pytest.raises(ValueError, match="non-negative"):
        rank_learning_moments(transcript(), weights={"definition": -1})


def test_length_alone_does_not_create_educational_signals():
    rows = [{"start": 0, "end": 30, "text": "ordinary narration without any special cue tokens " * 3 + "continues."}]
    result = rank_learning_moments(rows)
    assert result
    features = result[0]["score_breakdown"]["features"]
    assert features["definition"] == 0
    assert features["worked_example"] == 0
    assert features["question_answer"] == 0


def test_optional_scene_visual_and_word_evidence_are_used_without_invention():
    rows = [{"start": 4, "end": 14, "text": "This concept means a value can be stored and then reused.",
             "words": [{"start": 4.1, "end": 4.5, "text": "This"}, {"start": 13.3, "end": 14, "text": "reused."}]}]
    candidate = rank_learning_moments(rows, scene_changes=[4.1, 14], visual_evidence=[{"start": 6, "end": 9, "text": "x = 2"}])[0]
    assert candidate["score_breakdown"]["features"]["visual_support"] == 100
    assert candidate["score_breakdown"]["features"]["boundaries"] == 100
    assert candidate["evidence"][0]["words"] == rows[0]["words"]
    assert not any("No sampled slide" in warning for warning in candidate["warnings"])


def test_out_of_duration_segments_are_not_ranked():
    result = rank_learning_moments([{"start": 10, "end": 20, "text": "A sufficiently long spoken thought which would otherwise make a useful lesson example."}], video_duration=15)
    assert result == []


def test_near_duplicate_explanations_receive_redundancy_penalty():
    repeated = [
        {"start": 0, "end": 20, "text": "For example, calculate the total value using the same formula and compare the final result."},
        {"start": 40, "end": 60, "text": "For example, calculate the total value using the same formula and compare the final result."},
    ]
    result = rank_learning_moments(repeated)
    assert len(result) == 2
    assert result[0]["score_breakdown"]["features"]["redundancy"] == 100
    assert result[1]["score_breakdown"]["features"]["redundancy"] == 0
    assert any("overlaps" in warning for warning in result[1]["warnings"])


def test_rerank_endpoint_persists_evidence_and_render_requires_approval(monkeypatch, tmp_path):
    from app import db, main
    from fastapi import HTTPException

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "learning.sqlite3")
    db.initialize()
    with db.connect() as conn:
        conn.execute("INSERT INTO users VALUES('u','teacher@example.com','hash','now')")
        conn.execute("INSERT INTO videos(id,user_id,name,file_path,mime_type,size_bytes,duration,status,created_at) VALUES('v','u','lesson.mp4','/tmp/lesson.mp4','video/mp4',1,60,'ready','now')")
        conn.execute("INSERT INTO transcript_segments(video_id,start,end,text) VALUES('v',0,18,'What is a variable? A variable stores a value because we can reuse it. For example, assign a value and use it again.')")

    result = main.rerank_video("v", main.LearningRerankRequest(target_duration=30), user_id="u")
    assert result["count"] >= 1
    clip = result["candidates"][0]
    assert clip["source_video_id"] == "v"
    assert clip["evidence"] and clip["score_breakdown"]["features"]
    with pytest.raises(HTTPException) as error:
        main.start_render(clip["id"], main.RenderRequest(), user_id="u")
    assert error.value.status_code == 409

    approved = main.approve_clip(clip["id"], user_id="u")
    assert approved["review_status"] == "approved"
    with db.connect() as conn:
        stored = conn.execute("SELECT review_status,evidence_json,score_breakdown_json FROM clips WHERE id=?", (clip["id"],)).fetchone()
    assert stored["review_status"] == "approved"
    assert '"start"' in stored["evidence_json"]
    assert '"weighted_points"' in stored["score_breakdown_json"]

    edited = main.update_clip(clip["id"], main.ClipUpdate(start=2, end=18, title="Edited lesson moment"), user_id="u")
    assert edited["review_status"] == "suggested"
    assert edited["evidence"][0]["start"] == 0
    assert any("not been rescored" in warning for warning in edited["warnings"])

import json
from pathlib import Path

import pytest

from app import pipeline


def fake_probe_result(width=1920, height=1080, audio=True):
    streams = [{"codec_type": "video", "width": width, "height": height, "avg_frame_rate": "30000/1001"}]
    if audio: streams.append({"codec_type": "audio", "channels": 2})
    return {"streams": streams, "format": {"duration": "20"}}


@pytest.mark.parametrize("width,height", [(1920, 1080), (1080, 1920)])
def test_ffprobe_reads_dimensions_duration_rate_and_audio(monkeypatch, tmp_path, width, height):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: type("R", (), {"stdout": json.dumps(fake_probe_result(width, height))})())
    result = pipeline.probe(tmp_path / "sample.mp4")
    assert (result["width"], result["height"]) == (width, height)
    assert result["duration"] == 20
    assert result["frame_rate"] == pytest.approx(29.97, rel=1e-3)
    assert result["has_audio"] is True


def test_ffprobe_supports_video_without_audio(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: type("R", (), {"stdout": json.dumps(fake_probe_result(audio=False))})())
    assert pipeline.probe(tmp_path / "silent.mp4")["has_audio"] is False


def test_invalid_media_has_clear_validation_error(monkeypatch, tmp_path):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: type("R", (), {"stdout": "{\"streams\":[],\"format\":{}}"})())
    with pytest.raises(RuntimeError, match="not a readable video"):
        pipeline.probe(tmp_path / "bad.mp4")


@pytest.mark.parametrize("mode", ["center", "blur", "slide"])
def test_render_produces_checked_vertical_output(monkeypatch, tmp_path, mode):
    source, output = tmp_path / "in.mp4", tmp_path / "out.mp4"
    source.write_bytes(b"fixture")
    calls = []
    monkeypatch.setattr(pipeline, "probe", lambda path: {"width": 1920, "height": 1080, "duration": 20, "frame_rate": 30, "has_audio": False} if path == source else {"width": 1080, "height": 1920, "duration": 10, "frame_rate": 30, "has_audio": False})
    monkeypatch.setattr(pipeline, "run", lambda args, **kwargs: calls.append(args))
    result = pipeline.render_reel(source, output, 0, 10, [], "School", "#aabbcc", .5, .5, mode, "boxed")
    assert (result["width"], result["height"]) == (1080, 1920)
    assert result["source_has_audio"] is False
    command = calls[0]
    assert "0:a?" in command
    assert "1080:1920" in command[command.index("-vf") + 1]
    if mode == "slide": assert "force_original_aspect_ratio=decrease" in command[command.index("-vf") + 1]
    if mode == "blur": assert "boxblur" in command[command.index("-vf") + 1]


def test_render_failure_is_not_reported_as_success(monkeypatch, tmp_path):
    source = tmp_path / "in.mp4"; source.write_bytes(b"fixture")
    monkeypatch.setattr(pipeline, "probe", lambda path: {"width": 1920, "height": 1080, "duration": 20, "frame_rate": 30, "has_audio": True})
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("encoder failed")))
    with pytest.raises(RuntimeError, match="encoder failed"):
        pipeline.render_reel(source, tmp_path / "out.mp4", 0, 10, [], "", "#aabbcc", .5, .5)

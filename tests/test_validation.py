from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from pathlib import Path

from classlens.assessment import (
    AssessmentError,
    calculate_overall_rating,
    evaluate_reference_predictions,
    validate_assessment_json,
)
from classlens.config import (
    DEFAULT_RUBRIC,
    gemini_permission_error,
    rubric_configure,
    validate_uploaded_file,
)
from classlens.gemini_assessment import assess_video_with_gemini
from classlens.report_pdf import build_assessment_pdf


class FakeUpload:
    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size


def _valid_report():
    return {
        "rating": "Average",
        "confidence": "Medium",
        "communication_language": "English",
        "language_confidence": "High",
        "summary": "The video shows a lesson with mixed observable evidence.",
        "dimensions": [
            {
                "name": name,
                "score": 3,
                "evidence": "The video contains observable evidence for a middle score.",
                "limitation": "Only the provided recording is available.",
            }
            for name in DEFAULT_RUBRIC
        ],
        "strengths": ["The lesson presents a clear topic."],
        "improvements": ["Add more checks for understanding."],
        "limitations": [],
    }


def test_validate_recording_file_accepts_video_and_rejects_audio():
    allowed, message = validate_uploaded_file(FakeUpload("lesson.mp4", 1024))
    assert allowed is True
    assert "accepted" in message.lower()

    allowed, message = validate_uploaded_file(FakeUpload("lesson.mp3", 1024))
    assert allowed is False
    assert "unsupported" in message.lower()


def test_validate_recording_file_rejects_oversized_file():
    allowed, message = validate_uploaded_file(FakeUpload("lesson.mp4", 500 * 1024 * 1024))
    assert allowed is False
    assert "exceeds" in message.lower()


def test_rubric_configuration_maintains_total_weight():
    config = rubric_configure({
        "Student interaction": 30,
        "Rapport and engagement": 25,
        "Class structure": 20,
        "Visual and technical quality": 15,
        "Clarity and delivery": 10,
    })
    assert abs(sum(config.values()) - 1.0) < 1e-9
    assert config["Student interaction"] == 0.30


def test_invalid_assessment_json_is_rejected():
    invalid = _valid_report()
    invalid["dimensions"][0]["score"] = 6
    try:
        validate_assessment_json(invalid, list(DEFAULT_RUBRIC))
        assert False, "An out-of-range dimension score must fail validation"
    except ValueError as exc:
        assert "integer from 1 to 5" in str(exc)


def test_assessment_requires_exact_complete_rubric():
    invalid = _valid_report()
    invalid["dimensions"].pop()
    try:
        validate_assessment_json(invalid, list(DEFAULT_RUBRIC))
        assert False, "Missing rubric dimensions must fail validation"
    except ValueError as exc:
        assert "exactly one entry" in str(exc)


def test_reference_predictions_compute_accuracy_and_confusion_matrix():
    examples = [("Good", "Good"), ("Average", "Good"), ("Poor", "Poor"), ("Excellent", "Excellent")]
    results = evaluate_reference_predictions(examples)
    assert results["total"] == 4
    assert results["accuracy"] == 0.75
    assert results["confusion_matrix"]["Average"]["Good"] == 1


def test_overall_rating_uses_weighted_dimension_scores_and_full_scale():
    names = list(DEFAULT_RUBRIC)

    def dimensions(scores):
        return [{"name": name, "score": score} for name, score in zip(names, scores)]

    low_score, low_rating = calculate_overall_rating(dimensions([1, 1, 1, 1, 1]))
    average_score, average_rating = calculate_overall_rating(dimensions([3, 3, 3, 3, 3]))
    good_score, good_rating = calculate_overall_rating(dimensions([4, 4, 4, 4, 4]))
    excellent_score, excellent_rating = calculate_overall_rating(dimensions([5, 5, 5, 5, 5]))

    assert low_score == 1 and low_rating == "Poor"
    assert average_score == 3 and average_rating == "Average"
    assert good_score == 4 and good_rating == "Good"
    assert excellent_score == 5 and excellent_rating == "Excellent"


def test_gemini_permission_requires_organizer_approval_and_user_confirmation():
    assert gemini_permission_error(True, "false") is not None
    assert gemini_permission_error(False, "true") is not None
    assert gemini_permission_error(True, "true") is None


def test_gemini_video_assessment_validates_result_and_deletes_remote_upload(tmp_path, monkeypatch):
    from google import genai

    video_path = tmp_path / "lesson.mp4"
    video_path.write_bytes(b"test video bytes")
    calls = {}

    class FakeFiles:
        def upload(self, file, config):
            calls["upload_mime_type"] = config["mime_type"]
            while file.read(1024):
                pass
            return SimpleNamespace(
                name="files/uploaded-video",
                uri="https://example.invalid/video",
                mime_type="video/mp4",
                state=SimpleNamespace(name="ACTIVE"),
            )

        def delete(self, name):
            calls["deleted_name"] = name

    class FakeInteractions:
        def create(self, **kwargs):
            calls["interaction"] = kwargs
            return SimpleNamespace(output_text=json.dumps(_valid_report()))

    class FakeClient:
        def __init__(self, api_key, http_options):
            assert api_key == "test-gemini-key"
            assert http_options == {"timeout": 600_000}
            self.files = FakeFiles()
            self.interactions = FakeInteractions()

    monkeypatch.setattr(genai, "Client", FakeClient)

    progress = []
    report = assess_video_with_gemini(
        str(video_path),
        "test-gemini-key",
        on_progress=progress.append,
    )
    assert report["rating"] == "Average"
    assert report["assessment_mode"] == "GEMINI VIDEO"
    assert report["modalities_analyzed"] == {"transcript": False, "video_frames": True}
    assert "frame_count" not in report
    assert calls["deleted_name"] == "files/uploaded-video"
    assert calls["upload_mime_type"] == "video/mp4"
    assert calls["interaction"]["input"][0]["type"] == "video"
    assert calls["interaction"]["response_format"]["mime_type"] == "application/json"
    assert progress[0].startswith("Starting secure video upload")
    assert any(message.startswith("Preparing upload: read ") for message in progress)
    assert progress[-1] == "Review complete."
    assert report["communication_language"] == "English"
    assert report["overall_score"] == 3
    assert report["rating"] == "Average"


def test_pdf_report_exports_language_rubric_and_review(tmp_path):
    report = _valid_report()
    report.update({
        "filename": "class-video.mp4",
        "communication_language": "English and Hindi",
        "language_confidence": "Medium",
        "overall_score": 3.0,
        "rating_method": "Rubric-weighted average, with four evidence-based categories.",
    })
    pdf = build_assessment_pdf(report)

    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 2000


def test_gemini_upload_timeout_returns_actionable_error(tmp_path, monkeypatch):
    import httpx
    from google import genai

    video_path = tmp_path / "lesson.mp4"
    video_path.write_bytes(b"test video bytes")

    class FakeFiles:
        def upload(self, **_kwargs):
            raise httpx.TimeoutException("request timed out")

    class FakeClient:
        def __init__(self, api_key, http_options):
            self.files = FakeFiles()

    monkeypatch.setattr(genai, "Client", FakeClient)

    try:
        assess_video_with_gemini(str(video_path), "test-gemini-key")
        assert False, "A provider timeout must be shown as an assessment error"
    except AssessmentError as exc:
        assert "timed out while uploading or reviewing" in str(exc)
        assert "try a smaller video" in str(exc)


def test_gemini_interaction_server_error_is_reported_and_upload_is_deleted(
    tmp_path, monkeypatch
):
    import httpx
    from google import genai
    from google.genai._gaos.lib.compat_errors import InternalServerError

    video_path = tmp_path / "lesson.mp4"
    video_path.write_bytes(b"test video bytes")
    calls = {}

    class FakeFiles:
        def upload(self, **_kwargs):
            return SimpleNamespace(
                name="files/uploaded-video",
                uri="https://example.invalid/video",
                mime_type="video/mp4",
                state=SimpleNamespace(name="ACTIVE"),
            )

        def delete(self, name):
            calls["deleted_name"] = name

    class FakeInteractions:
        def create(self, **_kwargs):
            request = httpx.Request("POST", "https://example.invalid/interactions")
            response = httpx.Response(500, request=request)
            raise InternalServerError(
                "Google Gemini encountered an internal server error.",
                response=response,
                body={},
            )

    class FakeClient:
        def __init__(self, api_key, http_options):
            self.files = FakeFiles()
            self.interactions = FakeInteractions()

    monkeypatch.setattr(genai, "Client", FakeClient)

    try:
        assess_video_with_gemini(str(video_path), "test-gemini-key")
        assert False, "A Gemini server error must be shown as an assessment error"
    except AssessmentError as exc:
        assert "Google Gemini request failed" in str(exc)

    assert calls["deleted_name"] == "files/uploaded-video"


def test_app_shows_only_gemini_video_review():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).parents[1] / "app.py").run()
    assert not app.exception
    assert len(app.file_uploader) == 1
    assert app.file_uploader[0].label == "Choose a video"
    assert app.file_uploader[0].proto.multiple_files is False
    assert [item.label for item in app.button] == ["Generate class review"]
    assert not app.radio
    assert not app.slider
    assert not app.form
    video_bytes = b"single test video"
    app.file_uploader[0].set_value(("class-video.mp4", video_bytes, "video/mp4"))
    app.run()
    upload_token = hashlib.sha256(video_bytes).hexdigest()[:16]
    report = _valid_report()
    report.update({
        "assessment_mode": "GEMINI VIDEO",
        "provider": "Google Gemini",
        "filename": "class-video.mp4",
        "communication_language": "English",
        "language_confidence": "High",
        "overall_score": 3,
        "rating_method": "Weighted score determines rating band.",
        "frame_summary": "Video analyzed directly.",
        "analysis_notes": [],
    })
    app.session_state["last_report"] = report
    app.session_state["_report_upload_token"] = upload_token
    app.run()
    assert not app.exception
    assert "Communication:" in " ".join(item.value for item in app.markdown)
    assert {item.label for item in app.download_button} == {"Download JSON", "Download PDF"}
    app.session_state["last_report"] = {
        "assessment_mode": "USER-GUIDED REVIEW",
        "modalities_analyzed": {},
    }
    app.session_state["_report_upload_token"] = "old-upload"
    app.run()
    assert "last_report" not in app.session_state


def test_new_video_clears_previous_report():
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_file(Path(__file__).parents[1] / "app.py").run()
    app.session_state["last_report"] = {
        "assessment_mode": "GEMINI VIDEO",
        "summary": "Previous video's review",
        "modalities_analyzed": {"transcript": False, "video_frames": True},
    }
    app.session_state["_report_upload_token"] = "previous-video"
    app.session_state["_active_upload_token"] = "previous-video"
    app.file_uploader[0].set_value(("new-lesson.mp4", b"new video content", "video/mp4"))
    app.run()

    assert not app.exception
    assert "last_report" not in app.session_state
    assert not any("Previous video's review" in item.value for item in app.markdown)

from __future__ import annotations

import io
import json
import logging
import mimetypes
import time
from pathlib import Path
from typing import Any, Callable

from .assessment import (
    ASSESSMENT_SCHEMA,
    CATEGORY_DEFINITIONS,
    DIMENSION_GUIDANCE,
    AssessmentError,
    calculate_overall_rating,
    validate_assessment_json,
)
from .config import DEFAULT_RUBRIC

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"
VIDEO_PROCESSING_TIMEOUT_SECONDS = 300


class _ProgressReader(io.IOBase):
    def __init__(
        self,
        source: io.BufferedReader,
        total_bytes: int,
        on_progress: Callable[[str], None] | None,
    ) -> None:
        self._source = source
        self._total_bytes = total_bytes
        self._on_progress = on_progress
        self._bytes_read = 0

    @property
    def name(self) -> str:
        return self._source.name

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._source.tell()

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        return self._source.seek(offset, whence)

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        self._bytes_read += len(chunk)
        if chunk and self._on_progress:
            self._on_progress(
                f"Preparing upload: read {self._bytes_read / (1024 * 1024):.1f} "
                f"of {self._total_bytes / (1024 * 1024):.1f} MB from disk; "
                "sending video chunks securely to Google..."
            )
        return chunk

    def close(self) -> None:
        if not self.closed:
            self._source.close()
            super().close()


def assess_video_with_gemini(
    video_path: str,
    api_key: str,
    model: str = DEFAULT_GEMINI_MODEL,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Upload a video to Gemini, validate its rubric assessment, then delete the upload."""
    if not video_path or not Path(video_path).is_file():
        raise AssessmentError("The video file for Gemini assessment is missing.")
    if not api_key:
        raise AssessmentError("Provide a Gemini API key before analyzing a video.")

    try:
        from google import genai
        from google.genai import errors
        import httpx

        try:
            from google.genai._gaos.lib.compat_errors import APIError as InteractionsAPIError
        except ImportError:
            InteractionsAPIError = errors.APIError
    except ImportError as exc:
        raise AssessmentError(
            "Gemini support is not installed. Install the project requirements and try again."
        ) from exc

    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": 600_000},
    )
    uploaded_file = None
    report = None
    provider_error = None
    assessment_error = None
    cleanup_error = None
    prompt = json.dumps({
        "task": "Assess this online class from the supplied video and its audio.",
        "rubric_weights": DEFAULT_RUBRIC,
        "category_definitions": CATEGORY_DEFINITIONS,
        "dimension_guidance": DIMENSION_GUIDANCE,
        "requested_dimensions": list(DEFAULT_RUBRIC),
        "instructions": [
            "Use the full rating scale honestly. Do not default to Good or avoid Average/Poor when evidence supports them.",
            "Score each rubric dimension independently from 1 to 5 using only observed evidence; do not inflate scores to sound encouraging.",
            "Return a provisional rating consistent with the rubric-weighted score bands: Poor <2.5, Average 2.5-<3.5, Good 3.5-<4.5, Excellent >=4.5. The application will calculate the final category from your dimension scores.",
            "Identify the predominant spoken language or languages used for instruction. If unclear or there is no intelligible speech, say so explicitly; do not infer language from names, identity, or accent.",
            "Return one provisional rating from Excellent, Good, Average, or Poor.",
            "Evaluate only observable evidence in this video. Do not invent student reactions or events.",
            "Distinguish absence of evidence from evidence of poor teaching.",
            "Cite concrete observations from the video or its audio for each dimension.",
            "Do not judge accent, identity, or personal appearance.",
            "When evidence is incomplete, lower confidence and explain the limitation.",
            "If a dimension is not observable in the supplied video, say so rather than guessing.",
        ],
    })

    try:
        if on_progress:
            file_size_mb = Path(video_path).stat().st_size / (1024 * 1024)
            on_progress(
                f"Starting secure video upload to Google Gemini "
                f"({file_size_mb:.1f} MB). Transfer time depends on your connection..."
            )
        file_size = Path(video_path).stat().st_size
        mime_type, _ = mimetypes.guess_type(video_path)
        if not mime_type or not mime_type.startswith("video/"):
            raise AssessmentError("Could not determine a supported video format for this file.")
        with open(video_path, "rb") as source:
            tracked_file = _ProgressReader(source, file_size, on_progress)
            uploaded_file = client.files.upload(
                file=tracked_file,
                config={"mime_type": mime_type},
            )
        deadline = time.monotonic() + VIDEO_PROCESSING_TIMEOUT_SECONDS
        while True:
            state = getattr(uploaded_file.state, "name", uploaded_file.state)
            if state == "ACTIVE":
                break
            if state == "FAILED":
                raise AssessmentError("Google could not process the uploaded video.")
            if time.monotonic() >= deadline:
                raise AssessmentError("Google video processing timed out. Try a shorter or smaller video.")
            if on_progress:
                on_progress(
                    f"Google is processing the uploaded video ({state or 'waiting'}). "
                    "This can take a few minutes for larger recordings..."
                )
            time.sleep(5)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if on_progress:
            on_progress("Video ready. Gemini is reviewing the class and preparing rubric scores...")
        interaction = client.interactions.create(
            model=model,
            input=[
                {
                    "type": "video",
                    "uri": uploaded_file.uri,
                    "mime_type": uploaded_file.mime_type,
                },
                {"type": "text", "text": prompt},
            ],
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ASSESSMENT_SCHEMA,
            },
        )
        response_text = interaction.output_text
        if not response_text:
            raise AssessmentError("Google Gemini returned an empty assessment.")
        if on_progress:
            on_progress("Gemini review received. Validating the assessment...")
        try:
            report = validate_assessment_json(
                json.loads(response_text),
                list(DEFAULT_RUBRIC),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            raise AssessmentError(f"Google Gemini returned an invalid report: {exc}") from exc
    except AssessmentError as exc:
        assessment_error = exc
    except (errors.APIError, InteractionsAPIError) as exc:
        provider_error = exc
    except httpx.TimeoutException as exc:
        provider_error = AssessmentError(
            "Google Gemini timed out while uploading or reviewing the video. "
            "Check your connection, try a smaller video, and retry."
        )
        provider_error.__cause__ = exc
    except httpx.HTTPError as exc:
        provider_error = AssessmentError(
            f"Network error while communicating with Google Gemini: {exc}"
        )
        provider_error.__cause__ = exc
    finally:
        if uploaded_file is not None:
            if on_progress:
                on_progress("Removing the temporary video copy from Google...")
            try:
                client.files.delete(name=uploaded_file.name)
            except (errors.APIError, InteractionsAPIError) as exc:
                cleanup_error = exc

    if provider_error is not None:
        if cleanup_error is not None:
            logger.error(
                "Gemini video upload cleanup also failed after provider error: %s",
                cleanup_error,
            )
        if isinstance(provider_error, AssessmentError):
            raise provider_error from provider_error.__cause__
        raise AssessmentError(f"Google Gemini request failed: {provider_error}") from provider_error
    if assessment_error is not None:
        if cleanup_error is not None:
            logger.error(
                "Gemini video upload cleanup also failed after assessment error: %s",
                cleanup_error,
            )
        raise assessment_error
    if cleanup_error is not None:
        raise AssessmentError(
            "The assessment completed, but Google could not confirm deletion of the uploaded video. "
            "Check the Google AI Studio Files page and remove it manually."
        ) from cleanup_error
    if report is None:
        raise AssessmentError("Google Gemini did not produce a validated assessment.")
    overall_score, rating = calculate_overall_rating(report["dimensions"])
    report["rating"] = rating
    report["overall_score"] = round(overall_score, 2)
    report["rating_method"] = (
        "Rubric-weighted average across the five dimensions: Poor (<2.5), "
        "Average (2.5-<3.5), Good (3.5-<4.5), Excellent (4.5-5.0)."
    )
    report.update({
        "assessment_mode": "GEMINI VIDEO",
        "provider": "Google Gemini",
        "file_type": Path(video_path).suffix.lower(),
        "modalities_analyzed": {"transcript": False, "video_frames": True},
        "frame_summary": "Video and embedded audio analyzed directly by Google Gemini; no local frames were sampled.",
        "analysis_notes": [
            "The video and its audio were sent to Google Gemini for analysis.",
            "The temporary provider upload was deleted after the request.",
        ],
    })
    report["limitations"].append(
        "This result is model-generated and may be inaccurate; review it alongside the original recording."
    )
    if on_progress:
        on_progress("Review complete.")
    return report

from __future__ import annotations

from typing import Any

from .config import DEFAULT_RUBRIC, VALID_CONFIDENCE, VALID_RATINGS

CATEGORY_DEFINITIONS = {
    "Excellent": "Consistently strong evidence of interaction, rapport, clear teaching, and appropriate structure, without major observed barriers.",
    "Good": "Effective overall teaching with some areas that could be improved.",
    "Average": "Mixed or inconsistent evidence, including noticeable gaps in interaction, clarity, engagement, or structure.",
    "Poor": "Substantial observable barriers to effective teaching, such as persistent communication problems, inadequate interaction, or significant technical disruptions.",
}

DIMENSION_GUIDANCE = {
    "Student interaction": "Individual questions, participation opportunities, checks for understanding, attention to different students, and responsiveness when observable.",
    "Rapport and engagement": "Welcoming and respectful communication, rapport, appropriate energy and pacing, and support for students.",
    "Class structure": "Introduction, logical progression, transitions, conclusion or recap, and relevant follow-up work where appropriate.",
    "Visual and technical quality": "Teacher visibility when relevant, useful materials, lighting, intelligible audio, and technical disruptions. Do not overvalue branding or appearance.",
    "Clarity and delivery": "Understandable explanations and instructions, relevant examples, appropriate pace, and observable clarity problems. Do not judge accent.",
}

DIMENSION_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "evidence": {"type": "string"},
        "limitation": {"type": "string"},
    },
    "required": ["name", "score", "evidence", "limitation"],
    "additionalProperties": False,
}
ASSESSMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "rating": {"type": "string", "enum": list(VALID_RATINGS)},
        "confidence": {"type": "string", "enum": list(VALID_CONFIDENCE)},
        "communication_language": {"type": "string"},
        "language_confidence": {"type": "string", "enum": list(VALID_CONFIDENCE)},
        "summary": {"type": "string"},
        "dimensions": {"type": "array", "items": DIMENSION_SCHEMA},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "improvements": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "rating",
        "confidence",
        "communication_language",
        "language_confidence",
        "summary",
        "dimensions",
        "strengths",
        "improvements",
        "limitations",
    ],
    "additionalProperties": False,
}


class AssessmentError(RuntimeError):
    """Raised when a reliable, validated AI assessment cannot be produced."""


def validate_assessment_json(payload: Any, expected_dimensions: list[str] | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Assessment output must be a JSON object.")
    required = [
        "rating",
        "confidence",
        "communication_language",
        "language_confidence",
        "summary",
        "dimensions",
        "strengths",
        "improvements",
        "limitations",
    ]
    if any(key not in payload for key in required):
        missing = [key for key in required if key not in payload]
        raise ValueError(f"Missing required assessment fields: {', '.join(missing)}")

    if payload["rating"] not in VALID_RATINGS:
        raise ValueError(f"Invalid rating: {payload['rating']}")
    if payload["confidence"] not in VALID_CONFIDENCE:
        raise ValueError(f"Invalid confidence level: {payload['confidence']}")
    if not isinstance(payload["communication_language"], str) or not payload["communication_language"].strip():
        raise ValueError("Communication language must be a non-empty string.")
    if payload["language_confidence"] not in VALID_CONFIDENCE:
        raise ValueError(f"Invalid language confidence level: {payload['language_confidence']}")
    if not isinstance(payload["summary"], str) or not payload["summary"].strip():
        raise ValueError("Summary must be a non-empty string.")

    dimensions = payload["dimensions"]
    if not isinstance(dimensions, list):
        raise ValueError("Dimensions must be a list.")
    if expected_dimensions is not None and len(dimensions) != len(expected_dimensions):
        raise ValueError("Assessment must include exactly one entry for each rubric dimension.")

    seen_names = set()
    for dimension in dimensions:
        if not isinstance(dimension, dict):
            raise ValueError("Each dimension must be an object.")
        if not all(key in dimension for key in ("name", "score", "evidence", "limitation")):
            raise ValueError("Dimension missing one or more required fields.")
        name = dimension["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Dimension names must be non-empty strings.")
        if name in seen_names:
            raise ValueError(f"Duplicate assessment dimension: {name}")
        seen_names.add(name)
        score = dimension["score"]
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            raise ValueError(f"Dimension score must be an integer from 1 to 5: {score}")
        for field in ("evidence", "limitation"):
            if not isinstance(dimension[field], str) or not dimension[field].strip():
                raise ValueError(f"Dimension {field} must be a non-empty string.")

    if expected_dimensions is not None and seen_names != set(expected_dimensions):
        raise ValueError("Assessment dimensions do not match the configured rubric.")

    for field in ("strengths", "improvements", "limitations"):
        values = payload[field]
        if not isinstance(values, list) or not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(f"{field} must be a list of non-empty strings.")
    return payload


def calculate_overall_rating(dimensions: list[dict[str, Any]]) -> tuple[float, str]:
    """Calculate the rubric-weighted class rating using explicit category bands."""
    scores = {dimension["name"]: dimension["score"] for dimension in dimensions}
    if set(scores) != set(DEFAULT_RUBRIC):
        raise ValueError("Overall rating requires exactly the configured rubric dimensions.")
    weighted_score = sum(DEFAULT_RUBRIC[name] * scores[name] for name in DEFAULT_RUBRIC)
    if weighted_score >= 4.5:
        rating = "Excellent"
    elif weighted_score >= 3.5:
        rating = "Good"
    elif weighted_score >= 2.5:
        rating = "Average"
    else:
        rating = "Poor"
    return weighted_score, rating


def evaluate_reference_predictions(reference_examples: list[tuple[str, str]]) -> dict[str, Any]:
    """Calculate accuracy and a confusion matrix for labeled rating pairs."""
    labels = list(VALID_RATINGS)
    confusion = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    correct = 0
    for actual, predicted in reference_examples:
        if actual not in labels:
            raise ValueError(f"Unexpected actual label: {actual}")
        if predicted not in labels:
            raise ValueError(f"Unexpected predicted label: {predicted}")
        confusion[actual][predicted] += 1
        correct += actual == predicted
    total = len(reference_examples)
    return {
        "accuracy": correct / total if total else 0.0,
        "correct": correct,
        "total": total,
        "confusion_matrix": confusion,
    }

"""ClassLens AI package."""

from .assessment import validate_assessment_json
from .config import DEFAULT_RUBRIC

__all__ = [
    "DEFAULT_RUBRIC",
    "validate_assessment_json",
]

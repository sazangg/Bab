from app.modules.guardrails.detectors.base import TextDetector
from app.modules.guardrails.detectors.regex_pii import RegexPiiDetector

DEFAULT_PII_DETECTOR = "local_regex"

_DETECTORS: dict[str, TextDetector] = {
    RegexPiiDetector.name: RegexPiiDetector(),
}


def get_detector(name: str | None) -> TextDetector | None:
    return _DETECTORS.get(name or DEFAULT_PII_DETECTOR)


def list_detector_names() -> list[str]:
    return sorted(_DETECTORS)

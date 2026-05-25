import re

from app.modules.guardrails.detectors.base import DetectionResult

PII_PATTERNS = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    "phone": re.compile(r"\b(?:\+?\d[\d .().-]{7,}\d)\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
}


class RegexPiiDetector:
    name = "local_regex"

    async def detect(
        self,
        *,
        text: str,
        values: list[str],
        config: dict,
    ) -> DetectionResult:
        matched = [
            value
            for value in _normalized_values(values)
            if value in PII_PATTERNS and PII_PATTERNS[value].search(text)
        ]
        return DetectionResult(matched_values=matched)


def _normalized_values(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value.strip()]

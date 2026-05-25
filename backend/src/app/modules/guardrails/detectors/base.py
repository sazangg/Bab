from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class DetectionResult:
    matched_values: list[str] = field(default_factory=list)


class TextDetector(Protocol):
    name: str

    async def detect(
        self,
        *,
        text: str,
        values: list[str],
        config: dict,
    ) -> DetectionResult:
        pass

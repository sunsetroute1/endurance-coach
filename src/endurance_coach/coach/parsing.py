"""Parse LLM JSON output into typed coach responses."""

from __future__ import annotations

import json
import re
from typing import Any

from endurance_coach.domain.models import CoachRecommendation, CoachResponse


def _extract_json_payload(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("Coach LLM response must be a JSON object")
    return data


def parse_coach_response(content: str) -> CoachResponse:
    data = _extract_json_payload(content)
    recommendations = tuple(
        CoachRecommendation(
            category=str(item["category"]),
            action=str(item["action"]),
            rationale=str(item["rationale"]),
            metric_citations=tuple(str(key) for key in item.get("metric_citations", [])),
        )
        for item in data.get("recommendations", [])
    )
    metrics_used = tuple(str(key) for key in data.get("metrics_used", []))
    confidence = float(data.get("confidence", 0.7))
    return CoachResponse(
        explanation=str(data["explanation"]),
        recommendations=recommendations,
        metrics_used=metrics_used,
        confidence=max(0.0, min(1.0, confidence)),
    )

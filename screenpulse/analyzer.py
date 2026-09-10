"""
Two-stage local analysis of a flagged frame:

1. vision model  -> short natural-language scene description
2. text model    -> clean structured JSON {app, activity_summary, category}

The foreground window title / process name (when available) is given to both
stages as a strong hint for the `app` field.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .config import CATEGORIES, TEXT_MODEL, VISION_MODEL
from .ollama import OllamaClient, OllamaError

_VISION_PROMPT = (
    "This is a screenshot of a computer screen. In 1-3 sentences, describe what is "
    "visible: the foreground application or website, and what the user appears to be "
    "doing. Be concrete about visible UI, text, and window titles."
)

_STRUCTURE_SYSTEM = (
    "You convert a screen description into a compact JSON object. "
    "Output ONLY JSON, no prose, no markdown fences. "
    'Shape: {"app": string, "activity_summary": string, "category": string}. '
    "app = the foreground application or website name; trust the reported window "
    "info for this when it is given. "
    "activity_summary = one concise sentence about what the user is doing. "
    "category = exactly one of: " + ", ".join(CATEGORIES) + "."
)


@dataclass
class Analysis:
    app: str
    activity_summary: str
    category: str
    timestamp: datetime
    window_title: str = ""

    @classmethod
    def from_json_text(
        cls, raw: str, *, ts: Optional[datetime] = None, window_title: str = ""
    ) -> "Analysis":
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"no JSON object in model output: {raw!r}")
        data = json.loads(text[start : end + 1])
        category = str(data.get("category", "other")).lower().strip()
        if category not in CATEGORIES:
            category = "other"
        return cls(
            app=str(data.get("app", "unknown")).strip() or "unknown",
            activity_summary=str(data.get("activity_summary", "")).strip() or "(no summary)",
            category=category,
            timestamp=ts or datetime.now(),
            window_title=window_title,
        )


class VisionAnalyzer:
    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        *,
        vision_model: str = VISION_MODEL,
        text_model: str = TEXT_MODEL,
    ) -> None:
        self._client = client or OllamaClient()
        self._vision_model = vision_model
        self._text_model = text_model

    def analyze(
        self, jpeg_bytes: bytes, context: str = "", focus_hint: str = ""
    ) -> Analysis:
        prompt = _VISION_PROMPT
        if focus_hint:
            prompt += f"\n\nThe operating system reports the focused window as: {focus_hint}"
        if context:
            prompt += f"\n\nRecent prior activity for context: {context}"

        description = self._client.generate(
            self._vision_model, prompt, images=[jpeg_bytes], num_predict=200
        ).strip()

        detail = description
        if focus_hint:
            detail = f"Focused window (from the OS): {focus_hint}\n{description}"

        try:
            structured = self._client.generate(
                self._text_model,
                f"Screen description:\n{detail}\n\nReturn the JSON object.",
                system=_STRUCTURE_SYSTEM,
                json_format=True,
                num_predict=200,
            )
            return Analysis.from_json_text(structured, window_title=focus_hint)
        except (ValueError, json.JSONDecodeError, OllamaError):
            # Text model unavailable or unparseable output: fall back to a second
            # vision-model call for coarse structure.
            return self._vision_only(jpeg_bytes, description, focus_hint)

    def _vision_only(
        self, jpeg_bytes: bytes, description: str, focus_hint: str = ""
    ) -> Analysis:
        try:
            raw = self._client.generate(
                self._vision_model,
                "Given this screenshot, answer on one line exactly as:\n"
                "APP | CATEGORY | one-sentence summary\n"
                "where CATEGORY is one of: " + ", ".join(CATEGORIES),
                images=[jpeg_bytes],
                num_predict=80,
            ).strip()
            line = next((ln for ln in raw.splitlines() if "|" in ln), raw)
            app, category, summary = (p.strip() for p in (line.split("|") + ["", "", ""])[:3])
        except (OllamaError, ValueError):
            app, category, summary = "", "", ""
        category = category.lower()
        # A real process name beats whatever the vision model guessed.
        if focus_hint:
            app = focus_hint.split(" — ")[0] or app
        return Analysis(
            app=app or "unknown",
            activity_summary=summary or description[:200] or "(no summary)",
            category=category if category in CATEGORIES else "other",
            timestamp=datetime.now(),
            window_title=focus_hint,
        )

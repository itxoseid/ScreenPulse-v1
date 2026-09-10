"""Thin client for a local Ollama server. No API keys, no cloud calls."""

from __future__ import annotations

import base64
import re
from typing import Optional

import requests

from .config import OLLAMA_HOST

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_DANGLING_THINK_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaError(RuntimeError):
    pass


def strip_thinking(text: str) -> str:
    """Remove <think>...</think> reasoning emitted by qwen3 / deepseek-r1.

    Handles both well-formed blocks and the common case where the opening tag is
    missing but a closing </think> still separates reasoning from the answer.
    """
    text = _THINK_RE.sub("", text)
    if "</think>" in text.lower():
        text = _DANGLING_THINK_RE.sub("", text, count=1)
    return text.strip()


class OllamaClient:
    def __init__(self, host: str = OLLAMA_HOST, timeout: float = 120.0) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ health
    def is_up(self) -> bool:
        try:
            requests.get(f"{self.host}/api/tags", timeout=3).raise_for_status()
            return True
        except requests.RequestException:
            return False

    def available_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except requests.RequestException as exc:
            raise OllamaError(f"cannot reach Ollama at {self.host}: {exc}") from exc

    # ---------------------------------------------------------------- generate
    def generate(
        self,
        model: str,
        prompt: str,
        *,
        images: Optional[list[bytes]] = None,
        json_format: bool = False,
        system: Optional[str] = None,
        num_predict: int = 512,
        temperature: float = 0.2,
    ) -> str:
        user_msg: dict = {"role": "user", "content": prompt}
        if images:
            user_msg["images"] = [
                base64.standard_b64encode(b).decode("ascii") for b in images
            ]
        messages = ([{"role": "system", "content": system}] if system else []) + [user_msg]

        options = {"temperature": temperature, "num_predict": num_predict}
        chat_payload: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            # Disable chain-of-thought so reasoning models (qwen3, deepseek-r1)
            "think": False,  # answer directly instead of burning num_predict on <think>.
            "options": options,
        }
        if json_format:
            chat_payload["format"] = "json"

        try:
            r = requests.post(
                f"{self.host}/api/chat", json=chat_payload, timeout=self.timeout
            )
            if r.status_code == 400 and "think" in r.text.lower() and "support" in r.text.lower():
                chat_payload.pop("think", None)
                r = requests.post(
                    f"{self.host}/api/chat", json=chat_payload, timeout=self.timeout
                )
            if r.status_code == 400 and "does not support chat" in r.text:
                # Older model manifests: retry the legacy /api/generate endpoint.
                gen_payload: dict = {
                    "model": model,
                    "prompt": (f"{system}\n\n" if system else "") + prompt,
                    "stream": False,
                    "options": options,
                }
                if images:
                    gen_payload["images"] = user_msg["images"]
                if json_format:
                    gen_payload["format"] = "json"
                r = requests.post(
                    f"{self.host}/api/generate", json=gen_payload, timeout=self.timeout
                )
                if r.status_code >= 400:
                    raise OllamaError(
                        f"Ollama {model} HTTP {r.status_code}: {r.text[:300]} "
                        "(model may need re-pulling after an Ollama upgrade)"
                    )
                return strip_thinking(r.json().get("response", ""))
            if r.status_code >= 400:
                raise OllamaError(
                    f"Ollama {model} HTTP {r.status_code}: {r.text[:300]} "
                    "(model may need re-pulling after an Ollama upgrade)"
                )
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama request failed ({model}): {exc}") from exc

        return strip_thinking(r.json().get("message", {}).get("content", ""))

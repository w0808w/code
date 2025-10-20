from __future__ import annotations

import os
from typing import List, Dict, Any, Optional

from openai import OpenAI

from .config import get_openai_model


class GPTService:
    """Thin wrapper around OpenAI Chat Completions API."""

    def __init__(self, model: Optional[str] = None) -> None:
        self.client = OpenAI()
        self.model = model or get_openai_model()

    def complete(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        """Create a chat completion and return assistant text content."""
        params = {
            "model": self.model,
            "messages": messages,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**params)
        content = response.choices[0].message.content or ""
        return content.strip()



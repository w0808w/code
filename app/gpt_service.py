from __future__ import annotations

import os
from typing import List, Dict, Any, Optional

from openai import OpenAI

from .config import (
    get_openai_model,
    get_ai_provider,
    get_gemini_model,
    get_gemini_api_key,
    get_claude_model,
    get_anthropic_api_key,
)


class GPTService:
    """Unified wrapper around OpenAI and Gemini chat APIs.

    Provider selection order:
    - Explicit provider set via environment variable AI_PROVIDER ("openai"|"gemini").
    - Defaults to "openai".
    """

    def __init__(self, model: Optional[str] = None, provider: Optional[str] = None) -> None:
        self.provider = (provider or get_ai_provider()).lower()
        self.model = model  # interpreted per provider; falls back below
        # Lazy init per provider
        if self.provider == "openai":
            self._openai_client = OpenAI()
            self._openai_model = self.model or get_openai_model()
        elif self.provider == "gemini":
            self._gemini_client_initialized = False
            self._gemini_model = self.model or get_gemini_model()
        elif self.provider in {"claude", "anthropic"}:
            self._claude_client_initialized = False
            self._claude_model = self.model or get_claude_model()
        else:
            # Fallback to openai if unknown
            self.provider = "openai"
            self._openai_client = OpenAI()
            self._openai_model = self.model or get_openai_model()

    def complete(self, messages: List[Dict[str, str]], temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        if self.provider == "gemini":
            return self._complete_gemini(messages, temperature=temperature, max_tokens=max_tokens)
        if self.provider in {"claude", "anthropic"}:
            return self._complete_claude(messages, temperature=temperature, max_tokens=max_tokens)
        # default: openai
        params = {
            "model": self._openai_model,
            "messages": messages,
        }
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        response = self._openai_client.chat.completions.create(**params)
        content = response.choices[0].message.content or ""
        return content.strip()

    # --- Gemini ---
    def _ensure_gemini(self) -> None:
        if getattr(self, "_gemini_client_initialized", False):
            return
        import google.generativeai as genai  # lazy import

        api_key = get_gemini_api_key()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not configured")
        genai.configure(api_key=api_key)
        self._gemini = genai
        self._gemini_client_initialized = True

    def _complete_gemini(self, messages: List[Dict[str, str]], temperature: Optional[float], max_tokens: Optional[int]) -> str:
        self._ensure_gemini()
        system_instruction = None
        converted: List[Dict[str, Any]] = []

        for i, m in enumerate(messages):
            role = (m.get("role") or "").lower()
            content = m.get("content") or ""
            if role == "system" and system_instruction is None:
                system_instruction = content
                continue
            if role == "assistant":
                role = "model"
            elif role not in {"user", "model"}:
                role = "user"
            converted.append({
                "role": role,
                "parts": [{"text": content}],
            })

        generation_config: Dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = float(temperature)
        if max_tokens is not None:
            generation_config["max_output_tokens"] = int(max_tokens)

        model = self._gemini.GenerativeModel(self._gemini_model, system_instruction=system_instruction)
        resp = model.generate_content(converted, generation_config=generation_config or None)
        text = getattr(resp, "text", None) or ""
        return text.strip()

    # --- Claude (Anthropic) ---
    def _ensure_claude(self) -> None:
        if getattr(self, "_claude_client_initialized", False):
            return
        from anthropic import Anthropic  # lazy import

        api_key = get_anthropic_api_key()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self._claude = Anthropic(api_key=api_key)
        self._claude_client_initialized = True

    def _complete_claude(self, messages: List[Dict[str, str]], temperature: Optional[float], max_tokens: Optional[int]) -> str:
        self._ensure_claude()
        system_instruction = None
        converted: List[Dict[str, str]] = []

        for m in messages:
            role = (m.get("role") or "").lower()
            content = m.get("content") or ""
            if role == "system" and system_instruction is None:
                system_instruction = content
                continue
            if role not in {"user", "assistant"}:
                role = "user"
            converted.append({"role": role, "content": content})

        # Anthropics requires max_tokens; set a safe default if not provided
        mt = int(max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 1024)

        payload: Dict[str, Any] = {
            "model": self._claude_model,
            "messages": [
                {
                    "role": m["role"],
                    "content": [{"type": "text", "text": m["content"]}],
                }
                for m in converted
            ],
            "max_tokens": mt,
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if system_instruction:
            payload["system"] = system_instruction

        resp = self._claude.messages.create(**payload)
        # Concatenate text parts
        parts = getattr(resp, "content", [])
        out_text = ""
        for p in parts or []:
            t = getattr(p, "text", None)
            if isinstance(t, str):
                out_text += t
        return out_text.strip()



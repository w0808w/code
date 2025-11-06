import os
from typing import Optional

try:
    # Optional: load .env if present
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    # dotenv is optional; ignore if not installed
    pass


def get_openai_api_key() -> Optional[str]:
    return os.getenv("OPENAI_API_KEY")


def get_openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def get_server_port() -> int:
    try:
        return int(os.getenv("PORT", "8000"))
    except ValueError:
        return 8000



def get_ai_provider() -> str:
    return os.getenv("AI_PROVIDER", "openai").lower()


def get_gemini_api_key() -> Optional[str]:
    return os.getenv("GEMINI_API_KEY")


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def get_anthropic_api_key() -> Optional[str]:
    return os.getenv("ANTHROPIC_API_KEY")


def get_claude_model() -> str:
    return os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

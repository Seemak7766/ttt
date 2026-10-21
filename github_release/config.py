import os
from pathlib import Path
from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4o-mini"


def load_settings():
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return (
        os.getenv("OPENAI_API_KEY", "").strip(),
        os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_MODEL,
    )


def load_kakao_rest_api_key() -> str:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return os.getenv("KAKAO_REST_API_KEY", "").strip()


def load_langsmith_settings():
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return {
        "enabled": os.getenv("LANGSMITH_TRACING", "false").strip().lower() == "true",
        "api_key": os.getenv("LANGSMITH_API_KEY", "").strip(),
        "project": os.getenv("LANGSMITH_PROJECT", "").strip() or "travel-chatbot",
        "endpoint": os.getenv("LANGSMITH_ENDPOINT", "").strip() or "https://api.smith.langchain.com",
        "workspace_id": os.getenv("LANGSMITH_WORKSPACE_ID", "").strip() or None,
    }

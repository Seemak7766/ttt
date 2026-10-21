import os
from pathlib import Path
from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4o-mini"


def _cloud_value(name):
    try:
        import streamlit as st
        return st.secrets.get(name, "")
    except Exception:
        # 로컬에는 secrets.toml이 없어도 .env로 실행할 수 있습니다.
        return ""


def _setting(name, default=""):
    value = os.getenv(name, "").strip()
    if value:
        return value
    value = _cloud_value(name)
    return str(value).strip() if value is not None and str(value).strip() else default


def load_settings():
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return (
        _setting("OPENAI_API_KEY"),
        _setting("OPENAI_MODEL", DEFAULT_MODEL),
    )


def load_kakao_rest_api_key() -> str:
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return _setting("KAKAO_REST_API_KEY")


def load_langsmith_settings():
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    return {
        "enabled": _setting("LANGSMITH_TRACING", "false").lower() == "true",
        "api_key": _setting("LANGSMITH_API_KEY"),
        "project": _setting("LANGSMITH_PROJECT", "travel-chatbot"),
        "endpoint": _setting("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        "workspace_id": _setting("LANGSMITH_WORKSPACE_ID") or None,
    }

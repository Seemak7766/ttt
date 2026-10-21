import os
from pathlib import Path
from dotenv import load_dotenv

DEFAULT_MODEL = "gpt-4o-mini"
APP_BUILD = "2026.10.21-cloud-fix-2"


def configuration_status():
    """키 원문·길이·일부 문자열을 반환하지 않는 배포 진단."""
    load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
    cloud, error = {}, False
    try:
        import streamlit as st
        cloud = st.secrets.to_dict()
    except Exception:
        error = True
    def nested_has(node, name):
        if not isinstance(node, dict):
            return False
        return bool(node.get(name)) or any(nested_has(v, name) for v in node.values() if isinstance(v, dict))
    status = {}
    for name in ("OPENAI_API_KEY", "KAKAO_REST_API_KEY", "LANGSMITH_API_KEY"):
        if os.getenv(name, "").strip():
            status[name] = "설정됨 · 환경 변수/.env"
        elif isinstance(cloud.get(name), str) and cloud[name].strip():
            status[name] = "설정됨 · Secrets 최상위"
        elif nested_has(cloud, name):
            status[name] = "설정 위치 오류 · Secrets 최상위로 옮겨 주세요"
        else:
            status[name] = "없음 · Secrets를 읽지 못했거나 설정되지 않음" if error else "없음 · Secrets에 추가해 주세요"
    return status


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

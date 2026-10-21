"""LangSmith 추적: 명시적 활성화, 키 비공개, 설정 변경 시 클라이언트 갱신."""
from functools import lru_cache, wraps
import os

from langsmith import Client, traceable, tracing_context
from config import load_langsmith_settings


def redact(value):
    sensitive = {"api_key", "openai_api_key", "kakao_rest_api_key", "langsmith_api_key", "authorization", "password", "secret", "access_token"}
    if isinstance(value, dict):
        return {str(k): "[비공개]" if str(k).lower() in sensitive else redact(v) for k, v in value.items() if k != "runner"}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        for name in ("OPENAI_API_KEY", "KAKAO_REST_API_KEY", "LANGSMITH_API_KEY"):
            secret = os.getenv(name, "").strip()
            if secret:
                value = value.replace(secret, "[비공개]")
    return value


@lru_cache(maxsize=4)
def _client(api_key, endpoint, workspace_id):
    return Client(api_key=api_key, api_url=endpoint, workspace_id=workspace_id,
                  anonymizer=redact, hide_metadata=redact, timeout_ms=5000)


def configured_client(settings):
    return _client(settings["api_key"], settings["endpoint"], settings["workspace_id"])


def observed(name, *, run_type="chain"):
    def decorate(function):
        traced = traceable(name=name, run_type=run_type, process_inputs=redact, process_outputs=redact)(function)
        @wraps(function)
        def wrapped(*args, **kwargs):
            settings = load_langsmith_settings()
            enabled = settings["enabled"] and bool(settings["api_key"])
            client = None
            if enabled:
                try:
                    client = configured_client(settings)
                except Exception:
                    enabled = False
            with tracing_context(enabled=enabled, client=client, project_name=settings["project"], tags=["travel-chatbot"]):
                # 원래 함수 예외는 그대로 전달하며, 전송 실패로 함수를 재실행하지 않습니다.
                return traced(*args, **kwargs)
        return wrapped
    return decorate

"""Tests for application configuration and validation."""
import pytest
from pydantic import ValidationError, SecretStr
from app.core.config import Settings


def test_default_settings_instantiation(monkeypatch):
    """Verify that default settings instantiate without errors."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("FAST_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANSWER_LLM_API_KEY", raising=False)
    cfg = Settings(_env_file=None)
    assert cfg.CHUNK_SIZE_TOKENS == 650
    assert cfg.CHUNK_OVERLAP_TOKENS == 80
    assert cfg.RETRIEVAL_TOP_K == 15
    assert cfg.RERANK_TOP_N == 4
    assert cfg.EMBEDDING_PROVIDER == "local"
    assert cfg.EMBEDDING_MODEL == "BAAI/bge-m3"
    assert cfg.EMBEDDING_DIM == 1024
    assert cfg.LLM_PROVIDER == "openai_compatible"
    assert cfg.is_llm_configured() is False


def test_section_12_settings_presence():
    """Verify that EVERY setting from architecture.md section 12 exists."""
    cfg = Settings()
    expected_attrs = [
        "LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY", "FAST_MODEL", "ANSWER_MODEL",
        "FAST_LLM_PROVIDER", "FAST_LLM_BASE_URL", "FAST_LLM_API_KEY",
        "ANSWER_LLM_PROVIDER", "ANSWER_LLM_BASE_URL", "ANSWER_LLM_API_KEY",
        "LLM_TIMEOUT_SECONDS", "LLM_MAX_RETRIES",
        "EMBEDDING_PROVIDER", "EMBEDDING_BASE_URL", "EMBEDDING_API_KEY",
        "EMBEDDING_MODEL", "EMBEDDING_DIM", "RERANKER_MODEL",
        "CHUNK_SIZE_TOKENS", "CHUNK_OVERLAP_TOKENS",
        "RETRIEVAL_TOP_K", "RERANK_TOP_N", "RERANK_THRESHOLD",
        "HISTORY_MESSAGES", "SESSION_TTL_HOURS", "MAX_UPLOAD_MB",
        "ALLOWED_URL_DOMAINS", "ADMIN_EMAIL", "ADMIN_PASSWORD",
        "ENABLE_OCR", "RECONCILE_STALE_MINUTES", "ACCESS_TOKEN_MINUTES",
        "PASSWORD_MIN_LENGTH", "CORS_ORIGINS", "FALLBACK_MESSAGE", "GREETING_MESSAGE", "KB_TOPIC"
    ]
    for attr in expected_attrs:
        assert hasattr(cfg, attr), f"Missing setting {attr} from architecture §12"


def test_kb_topic_and_greeting_message(monkeypatch):
    """Verify that KB_TOPIC is dynamically formatted into GREETING_MESSAGE."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("FAST_LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANSWER_LLM_API_KEY", raising=False)

    cfg = Settings(KB_TOPIC="quantum computing", GREETING_MESSAGE=None, _env_file=None)
    assert "quantum computing" in cfg.GREETING_MESSAGE
    assert cfg.GREETING_MESSAGE == "Hi! I can answer questions about quantum computing. What would you like to know?"

    # Explicit override preserves custom message
    custom = "Welcome to the custom support assistant!"
    cfg_custom = Settings(KB_TOPIC="crypto", GREETING_MESSAGE=custom, _env_file=None)
    assert cfg_custom.GREETING_MESSAGE == custom


def test_secrets_never_printed():
    """Verify that secrets are masked and never exposed in repr or str output."""
    secret_value = "super-secret-key-12345"
    cfg = Settings(
        LLM_API_KEY=SecretStr(secret_value),
        ADMIN_PASSWORD=SecretStr(secret_value),
        JWT_SECRET_KEY=SecretStr(secret_value),
    )
    repr_str = repr(cfg)
    plain_str = str(cfg)
    assert secret_value not in repr_str
    assert secret_value not in plain_str


def test_invalid_setting_raises_clear_error():
    """Verify that invalid setting values raise ValidationError with clear explanation."""
    # Invalid chunk overlap > chunk size
    with pytest.raises(ValidationError) as exc_info:
        Settings(CHUNK_SIZE_TOKENS=500, CHUNK_OVERLAP_TOKENS=600)
    assert "CHUNK_OVERLAP_TOKENS" in str(exc_info.value)

    # Invalid chunk size <= 0
    with pytest.raises(ValidationError) as exc_info:
        Settings(CHUNK_SIZE_TOKENS=-50)
    assert "CHUNK_SIZE_TOKENS" in str(exc_info.value)

    # Invalid embedding provider
    with pytest.raises(ValidationError) as exc_info:
        Settings(EMBEDDING_PROVIDER="invalid_provider")
    assert "EMBEDDING_PROVIDER" in str(exc_info.value)

    # Invalid LLM provider
    with pytest.raises(ValidationError) as exc_info:
        Settings(LLM_PROVIDER="unsupported_provider")
    assert "LLM_PROVIDER" in str(exc_info.value)


def test_llm_configuration_guard():
    """Verify deferred LLM configuration checks."""
    cfg = Settings(LLM_API_KEY=None, FAST_MODEL=None, ANSWER_MODEL=None)
    assert cfg.is_llm_configured() is False
    with pytest.raises(ValueError) as exc:
        cfg.require_llm_configured()
    assert "LLM configuration incomplete" in str(exc.value)

    # Configured
    cfg_configured = Settings(
        LLM_API_KEY=SecretStr("sk-test"),
        FAST_MODEL="gpt-4o-mini",
        ANSWER_MODEL="gpt-4o",
    )
    assert cfg_configured.is_llm_configured() is True
    # Should not raise
    cfg_configured.require_llm_configured()

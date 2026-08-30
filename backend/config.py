from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ARIES-Voice API"
    app_env: str = "development"
    frontend_origin: str = "http://localhost:3000"

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    livekit_agent_name: str = "aries-interviewer"

    # Fully local AI services. Ollama handles language + embeddings; Speaches
    # serves Faster-Whisper and Kokoro through OpenAI-compatible endpoints.
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:4b"
    ollama_fast_model: str = "qwen3:1.7b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_embedding_dimensions: int = 768
    local_ai_timeout_seconds: float = 120.0

    speech_base_url: str = "http://localhost:8001/v1"
    speech_api_key: str = "local-not-needed"
    speech_stt_model: str = "Systran/faster-distil-whisper-small.en"
    speech_tts_model: str = "speaches-ai/Kokoro-82M-v1.0-ONNX"
    speech_tts_voice: str = "af_heart"

    # Used only for candidate/reviewer API access links. In production, set a
    # dedicated random value; the LiveKit secret is a safe local fallback.
    session_signing_secret: str = ""

    database_url: str = "postgresql+asyncpg://aries:aries@localhost:5432/aries"
    persistence_enabled: bool = True

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def access_secret(self) -> str:
        return self.session_signing_secret or self.livekit_api_secret

    @property
    def active_agent_name(self) -> str:
        """Versioned dispatch name prevents stale workers taking new sessions."""

        return f"{self.livekit_agent_name}-guided-v3"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

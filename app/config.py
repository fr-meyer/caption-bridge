from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mistral_api_key: str = ""
    transcribe_model: str = Field(
        default="voxtral-mini-transcribe-realtime-2602",
        validation_alias="MISTRAL_TRANSCRIBE_MODEL",
    )
    translate_model: str = Field(
        default="mistral-small-latest",
        validation_alias="MISTRAL_TRANSLATE_MODEL",
    )
    target_streaming_delay_ms: int = 1000
    audio_sample_rate: int = 16000
    pause_timeout_ms: int = 1500
    translation_context_segments: int = 5
    translation_timeout_ms: int = 10000
    readiness_poll_interval_ms: int = 3000
    client_disconnect_grace_ms: int = 45000
    reconnect_max_backoff_ms: int = 15000
    journal_dir: str = "./runs/.journal"
    recovery_export_dir: str = "./runs/recovered"
    host: str = "127.0.0.1"
    port: int = 8765
    export_dir: str = "./runs"
    realtime_base_url: str | None = Field(
        default=None,
        validation_alias="MISTRAL_REALTIME_BASE_URL",
    )


settings = AppConfig()

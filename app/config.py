from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    mistral_api_key: str = ""
    transcribe_model: str = Field(
        default="voxtral-mini-transcribe-realtime-2602",
        validation_alias="MISTRAL_TRANSCRIBE_MODEL",
    )
    translate_model: str = Field(
        default="mistral-medium-latest",
        validation_alias="MISTRAL_TRANSLATE_MODEL",
    )
    target_streaming_delay_ms: int = 1000
    asr_initial_timeout_ms: int = Field(default=10000, ge=100, le=60000, strict=True)

    @field_validator("asr_initial_timeout_ms", mode="before")
    @classmethod
    def parse_asr_initial_timeout(cls, value):
        if isinstance(value, str) and value.isascii() and value.isdecimal():
            return int(value)
        return value
    audio_sample_rate: int = 16000
    audio_queue_max_chunks: int = Field(default=50, ge=5, le=1000)
    pause_timeout_ms: int = Field(default=1500, ge=100, le=10000)
    fragment_merge_enabled: bool = Field(
        default=True,
        validation_alias="FRAGMENT_MERGE_ENABLED",
    )
    fragment_max_hold_ms: int = Field(
        default=3000,
        ge=0,
        le=15000,
        validation_alias="FRAGMENT_MAX_HOLD_MS",
    )
    fragment_min_chars: int = Field(
        default=15,
        ge=1,
        le=500,
        validation_alias="FRAGMENT_MIN_CHARS",
    )
    fragment_min_tokens: int = Field(
        default=3,
        ge=1,
        le=50,
        validation_alias="FRAGMENT_MIN_TOKENS",
    )
    translation_context_segments: int = 5
    translation_timeout_ms: int = Field(default=10000, ge=100, le=120000)
    translation_glm_timeout_ms: int = Field(
        default=20000, ge=100, le=120000,
        validation_alias="TRANSLATION_GLM_TIMEOUT_MS",
    )
    translation_drain_timeout_ms: int = Field(
        default=30000,
        ge=1000,
        le=300000,
        validation_alias="TRANSLATION_DRAIN_TIMEOUT_MS",
    )
    translation_provider: Literal["mistral"] = Field(
        default="mistral",
        validation_alias="TRANSLATION_PROVIDER",
    )
    translation_max_concurrency: int = Field(
        default=8,
        ge=1,
        le=64,
        validation_alias="TRANSLATION_MAX_CONCURRENCY",
    )
    translation_repair_max_attempts: int = Field(
        default=1, ge=0, le=1,
        validation_alias="TRANSLATION_REPAIR_MAX_ATTEMPTS",
    )
    readiness_poll_interval_ms: int = 3000
    client_disconnect_grace_ms: int = 45000
    ws_outbound_queue_max: int = Field(default=256, ge=32, le=4096)
    reconnect_base_backoff_ms: int = Field(default=1000, ge=0)
    reconnect_max_backoff_ms: int = Field(default=15000, ge=1)
    reconnect_max_attempts: int = Field(default=5, ge=1, le=20)
    reconnect_max_elapsed_ms: int = Field(default=60000, ge=1000)
    reconnect_jitter_factor: float = Field(default=0.25, ge=0.0, le=1.0)
    journal_dir: str = "./runs/.journal"
    recovery_export_dir: str = "./runs/recovered"
    reliability_dir: str = Field(
        default="./runs/reliability",
        validation_alias="RELIABILITY_DIR",
    )
    transcript_retention_days: int = Field(
        default=30, ge=1, le=3650,
        validation_alias="TRANSCRIPT_RETENTION_DAYS",
    )
    host: str = "127.0.0.1"
    port: int = 8765
    export_dir: str = "./runs"
    default_source_language: str = "auto"
    default_target_language: str = "en"
    realtime_base_url: str | None = Field(
        default=None,
        validation_alias="MISTRAL_REALTIME_BASE_URL",
    )
    tts_model: str = Field(
        default="voxtral-mini-tts-2603",
        validation_alias="MISTRAL_TTS_MODEL",
    )
    tts_enabled: bool = Field(
        default=True,
        validation_alias="MISTRAL_TTS_ENABLED",
    )
    tts_streaming_playback: bool = Field(
        default=False, validation_alias="MISTRAL_TTS_STREAMING_PLAYBACK",
    )
    tts_sample_rate: int = Field(
        default=24000,
        validation_alias="MISTRAL_TTS_SAMPLE_RATE",
    )
    tts_queue_max: int = Field(
        default=50, ge=1,
        validation_alias="MISTRAL_TTS_QUEUE_MAX",
    )
    tts_voice_id: str | None = Field(
        default=None,
        validation_alias="MISTRAL_TTS_VOICE_ID",
    )
    tts_transient_max_retries: int = Field(
        default=2,
        ge=0,
        le=5,
        validation_alias="MISTRAL_TTS_TRANSIENT_MAX_RETRIES",
    )
    tts_retry_base_delay_ms: int = Field(
        default=500,
        ge=0,
        validation_alias="MISTRAL_TTS_RETRY_BASE_DELAY_MS",
    )
    tts_retry_max_delay_ms: int = Field(
        default=2000,
        ge=1,
        validation_alias="MISTRAL_TTS_RETRY_MAX_DELAY_MS",
    )
    tts_retry_jitter_factor: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        validation_alias="MISTRAL_TTS_RETRY_JITTER_FACTOR",
    )
    translation_429_max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        validation_alias="TRANSLATION_429_MAX_RETRIES",
    )
    translation_429_base_delay_ms: int = Field(
        default=1000,
        ge=0,
        le=60000,
        validation_alias="TRANSLATION_429_BASE_DELAY_MS",
    )
    translation_429_max_delay_ms: int = Field(
        default=16000,
        ge=1,
        le=120000,
        validation_alias="TRANSLATION_429_MAX_DELAY_MS",
    )
    translation_429_jitter_factor: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        validation_alias="TRANSLATION_429_JITTER_FACTOR",
    )


settings = AppConfig()

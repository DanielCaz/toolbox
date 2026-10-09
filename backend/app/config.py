from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]  # repo root (toolbox/)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOOLBOX_")

    data_dir: Path = _ROOT / "data"
    static_dir: Path = _ROOT / "backend" / "static"
    max_upload_mb: int = 500
    job_ttl_min: int = 60
    workers: int = 2
    watch_dir: Path | None = None  # enables watch-folder mode: <watch_dir>/<pipeline-id>/
    watch_interval: float = 2.0  # seconds between scans
    # Optional AI tools. Nothing is sent anywhere unless a provider is configured.
    llm_provider: str = (
        ""  # "openai" (any OpenAI-compatible API, incl. Ollama / LM Studio) | "bedrock"
    )
    llm_model: str = ""  # model name, or the Bedrock model / inference-profile id
    llm_base_url: str = "https://api.openai.com/v1"  # openai provider only
    llm_api_key: str = ""  # openai provider only (blank is fine for local servers)
    llm_region: str = "us-east-1"  # bedrock provider only
    model_dir: Path | None = None  # where optional AI models (whisper, rembg) are cached

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def models_dir(self) -> Path:
        return self.model_dir or self.data_dir / "models"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()

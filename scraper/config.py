"""Environment-driven application settings."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@postgres:5432/upwork_demo",
    )
    api_host: str = os.getenv("API_HOST", "0.0.0.0")
    api_port: int = int(os.getenv("API_PORT", "5000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    browser_backend: str = os.getenv("BROWSER_BACKEND", "cdp").lower()
    cdp_url: str = os.getenv("CDP_URL", "http://host.docker.internal:9223")
    headless: bool = os.getenv("HEADLESS", "true").lower() in {"1", "true", "yes"}
    browser_timeout_ms: int = int(os.getenv("BROWSER_TIMEOUT_MS", "45000"))
    page_load_wait_ms: int = int(os.getenv("PAGE_LOAD_WAIT_MS", "15000"))
    request_delay_seconds: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.5"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))
    missing_threshold: int = int(os.getenv("MISSING_THRESHOLD", "2"))
    export_dir: str = os.getenv("EXPORT_DIR", "/app/exports")


settings = Settings()

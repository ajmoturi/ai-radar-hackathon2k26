"""Application configuration loaded from environment variables / .env file.

All settings are read via Pydantic-settings so they can be overridden by
environment variables at runtime without code changes.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from typing import Optional


class Settings(BaseSettings):
    # ------------------------------------------------------------------ #
    # LLM Provider                                                         #
    # ------------------------------------------------------------------ #
    # Switcher: "anthropic" | "azure_openai" | "openai"
    # Use "openai" for Groq, Ollama, Gemini, or any OpenAI-compatible API.
    llm_provider: str = Field(default="anthropic", env="LLM_PROVIDER")

    # Anthropic (Claude) — used when LLM_PROVIDER=anthropic
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-sonnet-4-6", env="ANTHROPIC_MODEL")

    # ------------------------------------------------------------------ #
    # Crawling                                                             #
    # ------------------------------------------------------------------ #
    # Set True to check robots.txt before crawling each domain (slower).
    respect_robots_txt: bool = Field(default=False, env="RESPECT_ROBOTS_TXT")

    # ------------------------------------------------------------------ #
    # Azure OpenAI — used when LLM_PROVIDER=azure_openai                  #
    # ------------------------------------------------------------------ #
    azure_openai_key: str = Field(default="", env="AZURE_OPENAI_KEY")
    azure_openai_endpoint: str = Field(default="", env="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str = Field(default="gpt-4o", env="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-08-01-preview", env="AZURE_OPENAI_API_VERSION")

    # ------------------------------------------------------------------ #
    # OpenAI-compatible — used when LLM_PROVIDER=openai                   #
    # Supports Groq, Ollama, Gemini, vanilla OpenAI, etc.                 #
    # ------------------------------------------------------------------ #
    openai_api_key: str = Field(default="", env="OPENAI_API_KEY")
    # Override base_url to point at Groq/Ollama/etc. endpoints.
    openai_base_url: str = Field(default="https://api.openai.com/v1", env="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o", env="OPENAI_MODEL")

    # ------------------------------------------------------------------ #
    # Email delivery                                                       #
    # ------------------------------------------------------------------ #
    smtp_host: str = Field(default="smtp.gmail.com", env="SMTP_HOST")
    smtp_port: int = Field(default=587, env="SMTP_PORT")
    smtp_user: str = Field(default="", env="SMTP_USER")
    smtp_pass: str = Field(default="", env="SMTP_PASS")
    email_from: str = Field(default="", env="EMAIL_FROM")
    # Comma-separated list of recipient email addresses.
    email_recipients: str = Field(default="", env="EMAIL_RECIPIENTS")
    # Optional SendGrid key — when set, overrides SMTP delivery.
    sendgrid_api_key: Optional[str] = Field(default=None, env="SENDGRID_API_KEY")

    # ------------------------------------------------------------------ #
    # Storage paths                                                        #
    # ------------------------------------------------------------------ #
    database_url: str = Field(default="sqlite:///./data/radar.db", env="DATABASE_URL")
    data_dir: str = Field(default="./data", env="DATA_DIR")
    pdf_dir: str = Field(default="./data/pdfs", env="PDF_DIR")
    snapshots_dir: str = Field(default="./data/snapshots", env="SNAPSHOTS_DIR")

    # ------------------------------------------------------------------ #
    # Scheduling (Prefect cron)                                            #
    # ------------------------------------------------------------------ #
    # Default: 6:30 AM Pacific Time daily.
    run_schedule: str = Field(default="30 6 * * *", env="RUN_SCHEDULE")
    run_timezone: str = Field(default="America/Los_Angeles", env="RUN_TIMEZONE")

    # ------------------------------------------------------------------ #
    # Prefect orchestration                                                #
    # ------------------------------------------------------------------ #
    # Leave empty to use Prefect local executor (no server required).
    prefect_api_url: Optional[str] = Field(default=None, env="PREFECT_API_URL")

    # ------------------------------------------------------------------ #
    # Frontend                                                             #
    # ------------------------------------------------------------------ #
    # Used to build dashboard deep-links in email bodies.
    frontend_url: str = Field(default="http://localhost:3000", env="FRONTEND_URL")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def recipients_list(self) -> list[str]:
        """Parse EMAIL_RECIPIENTS into a clean list, splitting on commas."""
        if not self.email_recipients:
            return []
        return [r.strip() for r in self.email_recipients.split(",") if r.strip()]

    def ensure_dirs(self):
        """Create data/pdf/snapshot directories if they do not already exist."""
        for d in [self.data_dir, self.pdf_dir, self.snapshots_dir]:
            Path(d).mkdir(parents=True, exist_ok=True)


# Singleton instance — import this everywhere instead of re-instantiating.
settings = Settings()
settings.ensure_dirs()

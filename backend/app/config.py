from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./beacon.db"
    chroma_dir: str = ".chroma"
    # Raw uploaded files are retained here (RAG readiness: raw source payload).
    data_dir: str = "data"
    openai_api_key: str = ""
    nora_model: str = "gpt-5-mini"
    # Demo mode: deterministic local embeddings + a labeled, template-composed
    # Nora. No OpenAI calls anywhere. For showing the product without billing;
    # never silently enabled and never mixed with live output.
    demo_mode: bool = False
    # When on, uploads schedule a background RAG sync so the knowledge base
    # updates automatically. Off by default (tests, and runs that use the
    # standalone `python -m app.cli.rag_worker` or the admin Process Queue
    # button instead).
    rag_autosync: bool = False
    # AI Visibility (Phase 11.5): external AI queries cost real money and hit
    # rate limits, unlike Beacon's deterministic modules. Fixed ceiling of live
    # query executions per property per UTC day; exceeding it fails honestly
    # rather than silently skipping. Stored-result reads are never limited.
    ai_visibility_daily_limit: int = 20
    # Model used when querying the ChatGPT connector live.
    ai_visibility_model: str = "gpt-5-mini"
    # Shared access key for hosted deployments (e.g. Render). Empty (the
    # default) means no auth - correct for local single-user use. When set,
    # every /api request except /api/health must carry it in the X-Beacon-Key
    # header or be rejected 401.
    access_key: str = ""
    # Extra allowed CORS origins for hosted deployments, comma-separated
    # (e.g. "https://beacon-frontend.onrender.com").
    cors_origins: str = ""

    model_config = SettingsConfigDict(
        env_prefix="BEACON_", env_file=".env", extra="ignore"
    )


settings = Settings()

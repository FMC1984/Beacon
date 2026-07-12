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
    # Google OAuth (GA4 Data API + Search Console auto-sync). Empty = the
    # Connect button explains what to configure instead of erroring.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Must exactly match an authorized redirect URI on the OAuth client.
    google_redirect_uri: str = "http://localhost:8600/api/google/callback"
    # Where the OAuth callback sends the browser back to (the frontend).
    frontend_url: str = "http://localhost:3100"
    # How many trailing days each sync pulls (replace-on-overlap by date).
    google_sync_days: int = 30
    # When on, a background task re-syncs every connected Google source daily.
    google_autosync: bool = False
    # When on, a weekly background task runs each property's active AI Visibility
    # standing prompts (spends OpenAI budget) and snapshots the score. Off by
    # default because it costs money; enable deliberately.
    ai_visibility_autorun: bool = False

    model_config = SettingsConfigDict(
        env_prefix="BEACON_", env_file=".env", extra="ignore"
    )


settings = Settings()

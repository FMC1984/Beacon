from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./beacon.db"
    chroma_dir: str = ".chroma"
    # Raw uploaded files are retained here (RAG readiness: raw source payload).
    data_dir: str = "data"
    openai_api_key: str = ""
    # Phase 19 slice 7: extra AI Visibility connectors. Each platform stays
    # not-live (no request is ever made) until its key is set.
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    perplexity_api_key: str = ""
    ai_gemini_model: str = "gemini-2.5-flash"
    ai_claude_model: str = "claude-opus-5"
    ai_claude_max_tokens: int = 4000
    ai_perplexity_model: str = "sonar"
    ai_web_search_max_uses: int = 5
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
    # Web search on visibility runs (question-set requirement): non-browsing
    # responses measure training recall, not retrieval, and produce false
    # misses. require_search discards runs where the model did not browse.
    ai_visibility_web_search: bool = True
    ai_visibility_require_search: bool = True
    # Output bills far above input; only enough response to carry citations.
    ai_visibility_max_output_tokens: int = 400
    ai_visibility_reasoning_effort: str = "low"
    # Phase 19: JSON string with the same shape as
    # reference_data/ai_provider_pricing.json ("models": {"provider:model":
    # {...rates...}}) overriding the shipped (null) rates. Empty = no override;
    # cost stays UNAVAILABLE until real prices are supplied.
    ai_pricing_overrides_json: str = ""
    # Phase 19 jobs runner: an in-process worker that drains the durable
    # `jobs` table every jobs_tick_seconds (leased, idempotent, retried with
    # backoff). ON by default: it only runs work that was explicitly queued.
    # The standalone `python -m app.cli.jobs_worker` is the same runner as a
    # separate process; turn this off when that is used.
    jobs_runner: bool = True
    jobs_tick_seconds: int = 15
    jobs_batch_limit: int = 20
    jobs_lease_seconds: int = 900
    # Default monthly observation allowance for the default organization
    # (Tina's decision: 300 runs/month; the per-property daily cap stays).
    ai_org_monthly_run_default: int = 300
    # Cosine threshold for grouping prompt wording variants into one cluster
    # (Phase 19 prompt library). Higher = stricter (more clusters).
    ai_cluster_threshold: float = 0.82
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
    # Google Business Profile reviews connector. OFF by default and deliberately
    # so: the GBP reviews API is access-restricted (Google must allowlist the
    # Cloud project) and uses the restricted business.manage scope. Adding that
    # scope to the shared consent screen before Google approves it would break
    # the working GA4/GSC connect flow, so GBP stays dark until this is flipped
    # on (after approval). When off, nothing about the current flow changes.
    google_gbp_enabled: bool = False
    # When on, a weekly background task runs each property's active AI Visibility
    # standing prompts (spends OpenAI budget) and snapshots the score. Off by
    # default because it costs money; enable deliberately.
    ai_visibility_autorun: bool = False
    # Phase 19 slice 5: the adaptive Observatory scheduler enqueues real
    # provider runs, so it is OFF until an operator enables it after reviewing
    # a dry-run plan (POST /api/ai-observatory/schedule/plan?dry_run=true).
    ai_scheduler_enabled: bool = False
    ai_scheduler_hour_utc: int = 9
    # When on, a daily background task freezes a Monthly Briefing snapshot for
    # any property whose previous calendar month has data but no snapshot yet.
    # ON by default: composing a briefing is deterministic and costs nothing
    # (no LLM, no external API) - unlike the AI Visibility autorun above.
    briefing_autosnapshot: bool = True

    model_config = SettingsConfigDict(
        env_prefix="BEACON_", env_file=".env", extra="ignore"
    )


settings = Settings()

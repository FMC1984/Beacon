"""Phase 1 acceptance: the initial Alembic migration builds the full schema on a
fresh database, and the migrated schema covers every table the models declare."""

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.db import Base
import app.models  # noqa: F401

EXPECTED_TABLES = {
    "companies",
    "properties",
    "uploads",
    "ga4_sessions_daily",
    "gsc_performance_daily",
    "gbp_metrics_daily",
    "paid_media_daily",
    "crm_leads",
    "rag_chunks",
    "nora_conversations",
    "nora_messages",
    "reports",
    "data_connections",
    "sync_jobs",
    "rag_sync_jobs",
    "property_content",
    "property_profile",
    "property_reviews",
    "ai_visibility_queries",
    "ai_visibility_prompts",
    "ai_visibility_score_history",
    "competitors",
}


def migrate_fresh_db(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    return create_engine(url)


def test_upgrade_head_creates_expected_tables(tmp_path):
    engine = migrate_fresh_db(tmp_path)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == EXPECTED_TABLES


def test_migration_matches_model_metadata(tmp_path):
    engine = migrate_fresh_db(tmp_path)
    migrated = set(inspect(engine).get_table_names()) - {"alembic_version"}
    declared = set(Base.metadata.tables.keys())
    assert declared == migrated


def test_key_columns_present(tmp_path):
    engine = migrate_fresh_db(tmp_path)
    insp = inspect(engine)
    ga4_cols = {c["name"] for c in insp.get_columns("ga4_sessions_daily")}
    # The classifier stamp columns are load-bearing for every later phase.
    assert {"is_ai_referral", "ai_platform", "upload_id"} <= ga4_cols
    lead_cols = {c["name"] for c in insp.get_columns("crm_leads")}
    assert {"lead_source_raw", "lease_signed_date", "external_lead_id"} <= lead_cols

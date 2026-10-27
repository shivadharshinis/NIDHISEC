"""The Alembic migrations must produce exactly the schema the models describe."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.models import Base

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_migrations_match_models(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url)
    config.attributes["configure_logger"] = False

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection, opts={"render_as_batch": True}), Base.metadata)
            assert diff == []
            triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'trigger'")).scalars().all()
            assert set(triggers) == {
                "audit_logs_no_update",
                "audit_logs_no_delete",
                "fdr_documents_evidence_immutable",
                "fdr_documents_withdrawal_final",
                "fdr_documents_no_delete",
                "verification_assignments_identity_immutable",
                "verification_assignments_final",
                "verification_assignments_no_delete",
                "verification_outcomes_no_update",
                "verification_outcomes_no_delete",
                "review_decisions_no_update",
                "review_decisions_no_delete",
                "screening_runs_no_update",
                "screening_runs_no_delete",
                "screening_findings_no_update",
                "screening_findings_no_delete",
                "screening_reviews_no_update",
                "screening_reviews_no_delete",
                "lifecycle_requests_identity_immutable",
                "lifecycle_requests_final",
                "lifecycle_requests_no_delete",
                "lifecycle_request_events_no_update",
                "lifecycle_request_events_no_delete",
                "notifications_content_immutable",
                "notifications_no_delete",
            }
    finally:
        engine.dispose()

    command.downgrade(config, "base")

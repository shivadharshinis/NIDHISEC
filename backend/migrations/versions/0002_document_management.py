"""document management: withdrawal fields, evidence protection

- fdr_documents.fdr_id: ON DELETE CASCADE -> RESTRICT (deleting an FDR must not remove evidence)
- withdrawal columns (documents are withdrawn with a reason, never deleted)
- check constraints, sha256 index
- triggers: evidence columns immutable, withdrawal final, rows cannot be deleted

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

import app.db.types


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DOCUMENT_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS fdr_documents_evidence_immutable "
    "BEFORE UPDATE OF fdr_id, document_type, original_filename, content_type, size_bytes, sha256, "
    "storage_key, uploaded_by_id, uploaded_at ON fdr_documents "
    "BEGIN SELECT RAISE(ABORT, 'fdr_documents evidence fields are immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS fdr_documents_withdrawal_final "
    "BEFORE UPDATE OF withdrawn_at, withdrawn_by_id, withdrawal_reason ON fdr_documents "
    "WHEN OLD.withdrawn_at IS NOT NULL "
    "BEGIN SELECT RAISE(ABORT, 'fdr_documents withdrawal cannot be changed'); END",
    "CREATE TRIGGER IF NOT EXISTS fdr_documents_no_delete BEFORE DELETE ON fdr_documents "
    "BEGIN SELECT RAISE(ABORT, 'fdr_documents rows cannot be deleted'); END",
]
TRIGGER_NAMES = ["fdr_documents_evidence_immutable", "fdr_documents_withdrawal_final", "fdr_documents_no_delete"]


def upgrade() -> None:
    with op.batch_alter_table('fdr_documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('withdrawn_at', app.db.types.UTCDateTime(), nullable=True))
        batch_op.add_column(sa.Column('withdrawn_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('withdrawal_reason', sa.String(length=500), nullable=True))
        batch_op.drop_constraint('fk_fdr_documents_fdr_id_fdrs', type_='foreignkey')
        batch_op.create_foreign_key(
            batch_op.f('fk_fdr_documents_fdr_id_fdrs'), 'fdrs', ['fdr_id'], ['id'], ondelete='RESTRICT'
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_fdr_documents_withdrawn_by_id_users'), 'users', ['withdrawn_by_id'], ['id'], ondelete='RESTRICT'
        )
        batch_op.create_check_constraint(batch_op.f('ck_fdr_documents_size_positive'), 'size_bytes > 0')
        batch_op.create_check_constraint(batch_op.f('ck_fdr_documents_sha256_length'), 'length(sha256) = 64')
        batch_op.create_check_constraint(
            batch_op.f('ck_fdr_documents_withdrawal_complete'),
            "(withdrawn_at IS NULL AND withdrawn_by_id IS NULL AND withdrawal_reason IS NULL)"
            " OR (withdrawn_at IS NOT NULL AND withdrawn_by_id IS NOT NULL AND withdrawal_reason IS NOT NULL)",
        )
        batch_op.create_index(batch_op.f('ix_fdr_documents_sha256'), ['sha256'], unique=False)

    # Created after the batch rebuild, which would otherwise drop them.
    for statement in DOCUMENT_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    for name in TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    with op.batch_alter_table('fdr_documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_fdr_documents_sha256'))
        batch_op.drop_constraint(batch_op.f('ck_fdr_documents_withdrawal_complete'), type_='check')
        batch_op.drop_constraint(batch_op.f('ck_fdr_documents_sha256_length'), type_='check')
        batch_op.drop_constraint(batch_op.f('ck_fdr_documents_size_positive'), type_='check')
        batch_op.drop_constraint(batch_op.f('fk_fdr_documents_withdrawn_by_id_users'), type_='foreignkey')
        batch_op.drop_constraint('fk_fdr_documents_fdr_id_fdrs', type_='foreignkey')
        batch_op.create_foreign_key('fk_fdr_documents_fdr_id_fdrs', 'fdrs', ['fdr_id'], ['id'], ondelete='CASCADE')
        batch_op.drop_column('withdrawal_reason')
        batch_op.drop_column('withdrawn_by_id')
        batch_op.drop_column('withdrawn_at')

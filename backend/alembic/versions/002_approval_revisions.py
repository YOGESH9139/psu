"""Allow a run to carry more than one human decision.

A rejected run can be re-planned once and re-submitted for approval. Keeping
every decision as its own revision preserves the full human-decision trail
instead of overwriting the first answer.
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_decisions",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    # The unique constraint was auto-named by Postgres when the column was
    # declared UNIQUE; drop it defensively so this migration is idempotent.
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            SELECT conname INTO constraint_name
            FROM pg_constraint
            WHERE conrelid = 'approval_decisions'::regclass
              AND contype = 'u';
            IF constraint_name IS NOT NULL THEN
                EXECUTE format(
                    'ALTER TABLE approval_decisions DROP CONSTRAINT %I', constraint_name
                );
            END IF;
        END $$;
        """
    )
    op.create_index(
        "ix_approval_decisions_run_id", "approval_decisions", ["run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_approval_decisions_run_id", table_name="approval_decisions")
    op.create_unique_constraint(
        "uq_approval_decisions_run_id", "approval_decisions", ["run_id"]
    )
    op.drop_column("approval_decisions", "revision")

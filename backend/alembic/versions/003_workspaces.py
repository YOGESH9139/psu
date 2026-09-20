"""Workspaces, follow-up threads and stored run results."""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("template", sa.String(64), nullable=False, server_default="blank"),
        sa.Column("banner", sa.String(32), nullable=False, server_default="INTERNAL"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column("runs", sa.Column("workspace", sa.String(36)))
    op.add_column("runs", sa.Column("parent_run_id", sa.String(36)))
    op.add_column("runs", sa.Column("result", sa.JSON))
    op.add_column("knowledge_chunks", sa.Column("workspace", sa.String(36)))
    op.create_index("ix_knowledge_chunks_workspace", "knowledge_chunks", ["workspace"])


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_workspace", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "workspace")
    op.drop_column("runs", "result")
    op.drop_column("runs", "parent_run_id")
    op.drop_column("runs", "workspace")
    op.drop_table("workspaces")

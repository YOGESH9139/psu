"""Initial schema — all tables."""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("goal", sa.Text, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("task_class", sa.String(64)),
        sa.Column("model_id", sa.String(64)),
        sa.Column("router_decision", sa.JSON),
        sa.Column("file_ids", sa.JSON),
        sa.Column("iteration_count", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "uploaded_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("original_filename", sa.String(256), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("local_path", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "artifacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("filename", sa.String(256), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("local_path", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(64), server_default="system"),
        sa.Column("model_id", sa.String(64)),
        sa.Column("tool_name", sa.String(128)),
        sa.Column("sanitized_args", sa.JSON),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("result_hash", sa.String(64)),
        sa.Column("artifact_hash", sa.String(64)),
        sa.Column("source_citations", sa.JSON),
        sa.Column("approval_decision", sa.String(32)),
        sa.Column("blocked_tool_attempt", sa.Boolean, server_default="false"),
        sa.Column("egress_check_result", sa.String(32)),
        sa.Column("metadata", sa.JSON),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False, unique=True),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("decided_by", sa.String(128), server_default="human"),
        sa.Column("artifact_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_file", sa.String(256), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("page_number", sa.Integer),
        sa.Column("heading", sa.String(512)),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("qdrant_point_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Indices
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_knowledge_chunks_source_hash", "knowledge_chunks", ["source_hash"])


def downgrade() -> None:
    op.drop_table("knowledge_chunks")
    op.drop_table("approval_decisions")
    op.drop_table("audit_events")
    op.drop_table("artifacts")
    op.drop_table("uploaded_files")
    op.drop_table("runs")

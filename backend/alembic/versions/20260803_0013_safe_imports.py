"""Add retained import jobs and row-level dry-run results."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260803_0013"
down_revision: Union[str, None] = "20260727_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("ImportJobs"):
        return
    op.create_table(
        "ImportJobs",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("EntityType", sa.String(50), nullable=False),
        sa.Column("Filename", sa.String(255), nullable=False),
        sa.Column("SourcePath", sa.String(500), nullable=False),
        sa.Column("UploadedBy", sa.Integer(), sa.ForeignKey("Users.Id", ondelete="RESTRICT"), nullable=False),
        sa.Column("Status", sa.String(50), nullable=False, server_default="Uploaded"),
        sa.Column("ColumnMapping", sa.JSON(), nullable=True),
        sa.Column("UpdateMode", sa.String(50), nullable=True),
        sa.Column("TransactionMode", sa.String(20), nullable=True),
        sa.Column("SourceHeaders", sa.JSON(), nullable=True),
        sa.Column("TotalRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ValidRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("InvalidRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("CreatedRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("UpdatedRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("SkippedRows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("StartedAt", sa.DateTime(), nullable=True),
        sa.Column("CompletedAt", sa.DateTime(), nullable=True),
        sa.Column("ErrorReportPath", sa.String(500), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("UpdatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_import_jobs_uploaded_by", "ImportJobs", ["UploadedBy"])
    op.create_index("ix_import_jobs_entity_status", "ImportJobs", ["EntityType", "Status"])
    op.create_index("ix_import_jobs_created_at", "ImportJobs", ["CreatedAt"])
    op.create_table(
        "ImportRowResults",
        sa.Column("Id", sa.Integer(), primary_key=True),
        sa.Column("ImportJobId", sa.Integer(), sa.ForeignKey("ImportJobs.Id", ondelete="CASCADE"), nullable=False),
        sa.Column("RowNumber", sa.Integer(), nullable=False),
        sa.Column("Status", sa.String(30), nullable=False),
        sa.Column("Action", sa.String(30), nullable=False),
        sa.Column("RawData", sa.JSON(), nullable=False),
        sa.Column("MappedData", sa.JSON(), nullable=True),
        sa.Column("Errors", sa.JSON(), nullable=True),
        sa.Column("DuplicateFields", sa.JSON(), nullable=True),
        sa.Column("TargetId", sa.Integer(), nullable=True),
        sa.Column("CreatedAt", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("ImportJobId", "RowNumber", name="uq_import_row_results_job_row"),
    )
    op.create_index("ix_import_row_results_job_status", "ImportRowResults", ["ImportJobId", "Status"])


def downgrade() -> None:
    op.drop_index("ix_import_row_results_job_status", table_name="ImportRowResults")
    op.drop_table("ImportRowResults")
    op.drop_index("ix_import_jobs_created_at", table_name="ImportJobs")
    op.drop_index("ix_import_jobs_entity_status", table_name="ImportJobs")
    op.drop_index("ix_import_jobs_uploaded_by", table_name="ImportJobs")
    op.drop_table("ImportJobs")

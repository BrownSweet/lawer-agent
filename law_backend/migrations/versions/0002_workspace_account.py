"""Persist the administrator and revocable login sessions."""
import sqlalchemy as sa
from alembic import op

revision = "0002_workspace_account"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspace_account",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspace_sessions",
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["workspace_account.id"]),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_workspace_sessions_expires_at", "workspace_sessions", ["expires_at"])


def downgrade():
    raise RuntimeError("Downgrade would remove administrator accounts. Restore a database backup instead.")

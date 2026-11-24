"""sources: choose how a page is fetched (plain HTTP or the optional browser service)

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMNs (with a default for existing rows) - no table rebuild.
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.add_column(sa.Column("render", sa.String(), nullable=False, server_default="static"))
        batch_op.add_column(sa.Column("wait_selector", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_column("wait_selector")
        batch_op.drop_column("render")

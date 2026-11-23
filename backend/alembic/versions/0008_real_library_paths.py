"""point the seeded tags at the real library folders (only rows still on the old placeholder paths)

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

MOVES = {
    "/media/movies/Tamil": "/Media_Server/05/Tamil Movies",
    "/media/movies/English": "/Media_Server/05/English Movies",
    "/media/movies/Dubbed": "/Media_Server/05/Dubbed Movies",
    "/media/movies/Indian": "/Media_Server/05/Indian Language Movies",
    "/media/tv": "/cloud/01",
    "/media/anime": "/cloud/02/Anime",
}


def upgrade() -> None:
    bind = op.get_bind()
    for old, new in MOVES.items():  # never touches a path the user already edited
        bind.execute(sa.text("UPDATE tags SET final_path = :new WHERE final_path = :old"), {"new": new, "old": old})


def downgrade() -> None:
    pass

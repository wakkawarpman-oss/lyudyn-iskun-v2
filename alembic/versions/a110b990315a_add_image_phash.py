"""Add image_phash to detected_events

Revision ID: a110b990315a
Revises: 973d066a7771
Create Date: 2026-09-03 03:00:00.000000

Hand-written, same reasoning as 973d066a7771: autogenerate against this
DB drags in an unrelated PostGIS TIGER-tables diff.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a110b990315a'
down_revision: Union[str, None] = '973d066a7771'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'detected_events',
        sa.Column('image_phash', sa.String(), nullable=True),
    )
    op.create_index(
        op.f('ix_detected_events_image_phash'),
        'detected_events',
        ['image_phash'],
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_detected_events_image_phash'), table_name='detected_events')
    op.drop_column('detected_events', 'image_phash')

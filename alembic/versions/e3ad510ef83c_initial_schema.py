"""initial_schema

Revision ID: e3ad510ef83c
Revises:
Create Date: 2026-03-23 15:53:36.955006

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3ad510ef83c'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all initial tables."""
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('username', sa.String(50), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('event_name', sa.String(100), nullable=False),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('event_token', sa.String(64), nullable=True),
        sa.Column('qr_code_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('event_token'),
    )
    op.create_index(op.f('ix_users_username'), 'users', ['username'])
    op.create_index(op.f('ix_users_event_token'), 'users', ['event_token'])

    # Media table
    op.create_table(
        'media',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('cloudinary_url', sa.Text(), nullable=False),
        sa.Column('cloudinary_public_id', sa.String(255), nullable=True),
        sa.Column('thumbnail_url', sa.Text(), nullable=True),
        sa.Column('media_type', sa.String(10), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('is_approved', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('rejection_reason', sa.String(255), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_media_user_id'), 'media', ['user_id'])

    # Share links table
    op.create_table(
        'share_links',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('token', sa.String(64), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default=sa.text('true')),
        sa.Column('view_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token'),
    )
    op.create_index(op.f('ix_share_links_token'), 'share_links', ['token'])

    # Upload sessions table
    op.create_table(
        'upload_sessions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('session_token', sa.String(64), nullable=True),
        sa.Column('device_info', sa.String(255), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('media_count', sa.Integer(), nullable=True, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_token'),
    )


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table('upload_sessions')
    op.drop_table('share_links')
    op.drop_index(op.f('ix_media_user_id'), table_name='media')
    op.drop_table('media')
    op.drop_index(op.f('ix_users_event_token'), table_name='users')
    op.drop_index(op.f('ix_users_username'), table_name='users')
    op.drop_table('users')

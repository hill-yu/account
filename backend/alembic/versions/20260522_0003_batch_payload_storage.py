"""add payload storage for collector ingestion batches

Revision ID: 20260522_0003
Revises: 20260522_0002
Create Date: 2026-05-22 18:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260522_0003"
down_revision = "20260522_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("collector_ingestion_batches", sa.Column("schema_version", sa.String(length=64), nullable=True))
    op.add_column("collector_ingestion_batches", sa.Column("payload_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("collector_ingestion_batches", "payload_json")
    op.drop_column("collector_ingestion_batches", "schema_version")

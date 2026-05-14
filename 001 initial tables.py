"""initial tables

Revision ID: 001
Revises:
Create Date: 2025-01-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asha_workers",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone_number", sa.String(), nullable=False, unique=True),
        sa.Column("pincode", sa.String(), nullable=True),
        sa.Column("district", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "patient_symptom_reports",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("patient_phone", sa.String(), nullable=False),
        sa.Column("call_sid", sa.String(), nullable=True, unique=True),
        sa.Column("patient_name", sa.String(), nullable=True),
        sa.Column("patient_age", sa.Integer(), nullable=True),
        sa.Column("primary_symptom", sa.String(), nullable=True),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("severity", sa.Integer(), nullable=True),
        sa.Column("associated_symptoms", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("medication_taken", sa.String(), nullable=True),
        sa.Column("urgency_level", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("raw_transcript", sa.Text(), nullable=True),
        sa.Column("asha_worker_id", sa.Integer(),
                  sa.ForeignKey("asha_workers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("patient_symptom_reports")
    op.drop_table("asha_workers")
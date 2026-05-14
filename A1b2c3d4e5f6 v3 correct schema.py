"""v3 correct schema matching models.py

Revision ID: a1b2c3d4e5f6
Revises: 7995cda64aed
Create Date: 2026-04-07

Drops any stale tables from previous migrations and recreates
asha_workers + patient_symptom_reports with the correct schema
that matches models.py exactly.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '7995cda64aed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop stale tables in dependency order
    op.execute('DROP TABLE IF EXISTS patient_symptom_reports CASCADE')
    op.execute('DROP TABLE IF EXISTS asha_workers CASCADE')
    op.execute('DROP TABLE IF EXISTS symptom_reports CASCADE')

    # ── asha_workers ─────────────────────────────────────────────────────────
    op.create_table(
        'asha_workers',
        sa.Column('id',           sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column('name',         sa.String(),   nullable=False),
        sa.Column('phone_number', sa.String(),   nullable=False, unique=True),
        sa.Column('pincode',      sa.String(),   nullable=True),   # optional
        sa.Column('district',     sa.String(),   nullable=True),   # optional
        sa.Column('created_at',   sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_asha_workers_id', 'asha_workers', ['id'], unique=False)
    op.create_index('ix_asha_workers_pincode', 'asha_workers', ['pincode'], unique=False)

    # ── patient_symptom_reports ───────────────────────────────────────────────
    op.create_table(
        'patient_symptom_reports',
        sa.Column('id',                  sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column('patient_phone',       sa.String(),   nullable=False),
        sa.Column('call_sid',            sa.String(),   nullable=True, unique=True),
        sa.Column('patient_name',        sa.String(),   nullable=True),
        sa.Column('patient_age',         sa.Integer(),  nullable=True),
        sa.Column('patient_pincode',     sa.String(),   nullable=True),
        sa.Column('primary_symptom',     sa.String(),   nullable=True),
        sa.Column('duration_days',       sa.Integer(),  nullable=True),
        sa.Column('severity',            sa.Integer(),  nullable=True),
        sa.Column('associated_symptoms', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('medication_taken',    sa.String(),   nullable=True),
        sa.Column('urgency_level',       sa.String(),   nullable=True),
        sa.Column('language',            sa.String(),   nullable=True),
        sa.Column('raw_transcript',      sa.Text(),     nullable=True),
        sa.Column('asha_worker_id',      sa.Integer(),
                  sa.ForeignKey('asha_workers.id'), nullable=True),
        sa.Column('to_phone',            sa.String(),   nullable=True),
        sa.Column('recording_url',       sa.String(),   nullable=True),
        sa.Column('created_at',          sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('ix_patient_symptom_reports_id',
                    'patient_symptom_reports', ['id'], unique=False)
    op.create_index('ix_patient_symptom_reports_patient_phone',
                    'patient_symptom_reports', ['patient_phone'], unique=False)


def downgrade() -> None:
    op.drop_table('patient_symptom_reports')
    op.drop_table('asha_workers')
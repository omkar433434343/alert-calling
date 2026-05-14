"""initial tables

Revision ID: 7995cda64aed
Revises: 2e9d19cf5526
Create Date: 2026-04-07 01:35:57.058161

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7995cda64aed'
down_revision: Union[str, None] = '2e9d19cf5526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old stale tables in dependency order using CASCADE
    op.execute('DROP TABLE IF EXISTS triage_records CASCADE')
    op.execute('DROP TABLE IF EXISTS patients CASCADE')
    op.execute('DROP TABLE IF EXISTS users CASCADE')

    # Create asha_workers table (IF NOT EXISTS — safe to re-run)
    op.execute("""
        CREATE TABLE IF NOT EXISTS asha_workers (
            id SERIAL PRIMARY KEY,
            name VARCHAR NOT NULL,
            phone_number VARCHAR NOT NULL,
            pincode VARCHAR NOT NULL,
            district VARCHAR NOT NULL,
            state VARCHAR NOT NULL,
            created_at TIMESTAMP
        )
    """)
    op.execute('CREATE INDEX IF NOT EXISTS ix_asha_workers_pincode ON asha_workers (pincode)')

    # Create patient_symptom_reports table (IF NOT EXISTS — safe to re-run)
    op.execute("""
        CREATE TABLE IF NOT EXISTS patient_symptom_reports (
            id SERIAL PRIMARY KEY,
            patient_phone VARCHAR NOT NULL,
            call_sid VARCHAR NOT NULL UNIQUE,
            primary_symptom VARCHAR NOT NULL,
            duration_days INTEGER,
            severity INTEGER,
            associated_symptoms TEXT,
            medication_taken VARCHAR,
            urgency_level VARCHAR NOT NULL,
            language VARCHAR NOT NULL,
            created_at TIMESTAMP
        )
    """)
    op.execute('CREATE INDEX IF NOT EXISTS ix_patient_symptom_reports_patient_phone ON patient_symptom_reports (patient_phone)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS patient_symptom_reports CASCADE')
    op.execute('DROP TABLE IF EXISTS asha_workers CASCADE')
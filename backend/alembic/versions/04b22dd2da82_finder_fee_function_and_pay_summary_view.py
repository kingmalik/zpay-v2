"""finder fee function and pay_summary view

Revision ID: 04b22dd2da82
Revises: 348ee4aac5d1
Create Date: 2025-09-19 22:42:03.245892

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04b22dd2da82'
down_revision: Union[str, Sequence[str], None] = '348ee4aac5d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.execute("""
    CREATE OR REPLACE FUNCTION get_finder_fee_pct(p_person_id INT, p_when TIMESTAMPTZ)
    RETURNS NUMERIC AS $$
      SELECT cr.pct_fee
      FROM commission_rule cr
      WHERE (cr.person_id = p_person_id OR cr.person_id IS NULL)
        AND cr.name = 'finder_fee'
        AND cr.effective_from <= p_when::date
        AND (cr.effective_to IS NULL OR cr.effective_to >= p_when::date)
      ORDER BY (cr.person_id IS NULL) ASC, cr.effective_from DESC
      LIMIT 1;
    $$ LANGUAGE sql STABLE;
    """)

    op.execute("""
    CREATE OR REPLACE VIEW pay_summary AS
    WITH ride_enriched AS (
      SELECT
        r.ride_id,
        r.person_id,
        (r.ride_start_ts)::date AS ride_date,
        (COALESCE(r.base_fare,0) + COALESCE(r.tips,0) + COALESCE(r.adjustments,0)) AS gross_before_fee,
        COALESCE(get_finder_fee_pct(r.person_id, r.ride_start_ts), 0) AS pct_fee
      FROM ride r
    )
    SELECT
      p.person_id,
      p.full_name,
      DATE_TRUNC('week', ride_date)::date AS week_start,
      COUNT(*) AS rides_count,
      ROUND(SUM(gross_before_fee), 2) AS gross_before_fee,
      ROUND(SUM(gross_before_fee * pct_fee), 2) AS finder_fee_amount,
      ROUND(SUM(gross_before_fee * (1 - pct_fee)), 2) AS net_after_fee
    FROM ride_enriched re
    JOIN person p ON p.person_id = re.person_id
    GROUP BY p.person_id, p.full_name, DATE_TRUNC('week', ride_date)
    ORDER BY week_start DESC, p.full_name;
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS pay_summary;")
    op.execute("DROP FUNCTION IF EXISTS get_finder_fee_pct(INT, TIMESTAMPTZ);")

"""Backfill manual rides: set source='manual' and net_pay=0 for rows where z_rate_source='manual'.

Revision ID: zb2c3d4e5f6g7
Revises: za1b2c3d4e5f6
Create Date: 2026-04-28

Background
----------
Bug A caused manual rides to be stored with source='firstalt' or 'maz' instead of 'manual'.
Bug B caused net_pay to be set to z_rate instead of 0, falsely inflating partner_paid totals.

This migration corrects both fields on all historical rows identified by z_rate_source='manual'
(the only reliable discriminator that was set correctly from the start).

WARNING — run interactively with Malik present
----------------------------------------------
After upgrade, the ``partner_paid`` aggregate on /payroll-history will drop by the sum of
net_pay that was previously set on these rows.  Before running, snapshot::

    SELECT payroll_batch_id, SUM(net_pay) AS net_pay_before
    FROM ride
    WHERE z_rate_source = 'manual'
    GROUP BY payroll_batch_id
    ORDER BY payroll_batch_id;

Reconcile against W14/W15 hand-verified totals before declaring done.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "zb2c3d4e5f6g7"
down_revision: Union[str, Sequence[str], None] = "za1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        UPDATE ride
        SET
            source  = 'manual',
            net_pay = 0
        WHERE z_rate_source = 'manual'
          AND (source != 'manual' OR net_pay != 0);
    """)


def downgrade() -> None:
    # A clean reverse is not possible: the original source value ('firstalt' or 'maz')
    # was never recorded before the upgrade overwrote it, so we cannot restore it.
    # net_pay restoration would also require knowing the pre-fix z_rate values per row.
    # No-op intentional — re-running upgrade() again is idempotent and safe.
    pass

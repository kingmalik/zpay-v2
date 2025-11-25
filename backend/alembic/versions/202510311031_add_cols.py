from alembic import op
import sqlalchemy as sa

revision = "202510311031"
down_revision = "202510292109"  
branch_labels = None
depends_on = None

def upgrade():

    # 2) Function: net_pay_for_ride
    op.execute("""
    CREATE OR REPLACE FUNCTION net_pay_for_ride(p_person_id int, p_ride_id bigint)
    RETURNS numeric
    LANGUAGE plpgsql
    AS $$
    DECLARE
      v_net   numeric;
      v_base  numeric;
      v_tips  numeric;
      v_adj   numeric;
      v_fee   numeric := 0;
      v_gross numeric;
      has_pay_summary boolean := FALSE;
    BEGIN
      SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public'
          AND table_name='pay_summary'
          AND column_name IN ('ride_id','net_pay')
      ) INTO has_pay_summary;

      IF has_pay_summary THEN
        SELECT ps.net_pay INTO v_net
          FROM pay_summary ps
         WHERE ps.ride_id = p_ride_id
           AND (ps.person_id IS NULL OR ps.person_id = p_person_id)
         LIMIT 1;
        IF v_net IS NOT NULL THEN
          RETURN v_net;
        END IF;
      END IF;

      SELECT base_fare, tips, adjustments
        INTO v_base, v_tips, v_adj
        FROM ride
       WHERE ride_id = p_ride_id AND person_id = p_person_id;

      v_gross := COALESCE(v_base,0) + COALESCE(v_tips,0) + COALESCE(v_adj,0);

      IF to_regprocedure('finder_fee(numeric)') IS NOT NULL THEN
        SELECT finder_fee(v_base) INTO v_fee;
      ELSIF to_regprocedure('finder_fee(numeric,integer)') IS NOT NULL THEN
        EXECUTE 'SELECT finder_fee($1,$2)' INTO v_fee USING v_base, p_person_id;
      END IF;

      RETURN v_gross - COALESCE(v_fee,0);
    END
    $$;
    """)

    # 3) View: ride_report_v
    op.execute("""
    CREATE OR REPLACE VIEW ride_report_v AS
    SELECT
      r.person_id,
      p.full_name                         AS person,
      p.person_code                       AS code,
      (r.ride_start_ts::date)             AS date,
      r.source_ref                        AS key,
      r.service_name                      AS name,
      ROUND(r.distance_km * 0.621371, 1)  AS miles,
      (COALESCE(r.base_fare,0)
       + COALESCE(r.tips,0)
       + COALESCE(r.adjustments,0))       AS gross,
      net_pay_for_ride(r.person_id, r.ride_id) AS net_pay
    FROM ride r
    JOIN person p ON p.person_id = r.person_id;
    """)

def downgrade():
    # drop view then function then constraints/columns
    op.execute("DROP VIEW IF EXISTS ride_report_v;")
    op.execute("DROP FUNCTION IF EXISTS net_pay_for_ride(int, bigint);")
    op.drop_constraint("person_person_code_uniq", "person", type_="unique")
    op.drop_column("person", "person_code")
    op.drop_column("ride", "service_name")

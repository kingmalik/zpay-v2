from sqlalchemy import (
    Column, Integer, BigInteger, Text, Boolean, Date, DateTime, ForeignKey, Numeric,
    Index, text, String, JSON, LargeBinary
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import DATERANGE
from datetime import datetime, timezone
Base = declarative_base()


class Person(Base):
    __tablename__ = "person"

    person_id = Column(Integer, primary_key=True)
    external_id = Column(Text, nullable=True)
    full_name = Column(Text, nullable=False)
    email = Column(Text)
    phone = Column(Text)
    home_address = Column(Text)
    firstalt_driver_id = Column(Integer)
    everdriven_driver_id = Column(Integer)
    paycheck_code = Column(Text, nullable=True)
    # Maz-side Paychex worker ID (EverDriven batches); paycheck_code above is Acumen-side (FirstAlt).
    paycheck_code_maz = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    # 'active' | 'dormant' (no rides this year, keep data) | 'inactive' (manually deactivated)
    status = Column(Text, nullable=False, server_default=text("'active'"))
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))
    notes = Column(Text, nullable=True)
    language = Column(String(20), nullable=True)  # "en", "ar", "am" — preferred language for automated calls
    vehicle_make = Column(Text, nullable=True)
    vehicle_model = Column(Text, nullable=True)
    vehicle_year = Column(Integer, nullable=True)
    vehicle_plate = Column(Text, nullable=True)
    vehicle_color = Column(Text, nullable=True)
    # tin and license_number REMOVED — contained SSN data, wiped for security
    sex = Column(String(10), nullable=True)  # "M" | "F" — auto-filled from FirstAlt, editable
    # FirstAlt live compliance data — synced every 6 hours by firstalt_compliance.py
    firstalt_compliance = Column(JSON, nullable=True)
    # EverDriven / Contractor Compliance fields
    contractor_compliance_id = Column(String(100), nullable=True)
    cc_compliance = Column(JSON, nullable=True)
    # Drug test consent (Priority Solutions)
    drug_test_agreement_id = Column(Text, nullable=True)
    drug_test_sent_at = Column(DateTime(timezone=True), nullable=True)
    drug_test_signed_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 2 — operator alert controls. Null = no mute active.
    # Shape: {"muted_until": "2026-05-01T00:00:00Z" | null, "muted_reason": str | null}
    # Driver-facing SMS is never affected — only admin escalation calls.
    alert_profile = Column(JSON, nullable=True)

    rides = relationship("Ride", back_populates="person")

    __table_args__ = (
        Index("uq_person_external_id", "external_id", unique=True),
        # partial unique index by normalized name when external_id is null:
        # this index is created in Alembic via sa.text(...), so we don't repeat here.
    )


class PayrollBatch(Base):
    __tablename__ = "payroll_batch"

    payroll_batch_id = Column(Integer, primary_key=True)
    source = Column(Text, nullable=False)
    company_name = Column(Text, nullable=False)
    batch_ref = Column(Text)
    currency = Column(Text, nullable=False, server_default=text("'USD'"))
    period_start = Column(Date)
    period_end = Column(Date)
    week_start = Column(Date)
    week_end = Column(Date)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text)
    # Workflow status: uploaded, rates_review, payroll_review, approved, export_ready, stubs_sending, complete
    status = Column(Text, nullable=False, server_default=text("'uploaded'"))
    paychex_exported_at = Column(DateTime(timezone=True), nullable=True)
    sp_file_bytes = Column(LargeBinary, nullable=True)
    # Partner gross billing total for this batch. Set on reconstruction imports
    # where per-ride partner gross is not recoverable (only aggregate is known).
    # When set, payroll_history uses this for profit calculation instead of
    # summing ride.gross_pay. NULL = use sum(ride.gross_pay) as before.
    partner_gross_total = Column(Numeric(12, 2), nullable=True)

    rides = relationship("Ride", back_populates="batch")
    workflow_logs = relationship("BatchWorkflowLog", back_populates="batch", cascade="all, delete-orphan")


class ZRateService(Base):
    __tablename__ = "z_rate_service"

    z_rate_service_id = Column(Integer, primary_key=True)
    source = Column(Text, nullable=True)
    company_name = Column(Text, nullable=True)
    service_key = Column(String(255), nullable=False, unique=True, index=True)
    service_name = Column(Text, nullable=False)

    currency = Column(Text, nullable=False, server_default=text("'USD'"))
    default_rate = Column(Numeric(12, 2), nullable=False)
    # Per-service rate that applies specifically to late-cancellation rides
    # (when partner net_pay is 40–55% of default_rate). Null = no late-cancel override.
    late_cancellation_rate = Column(Numeric(12, 2), nullable=True)
    # Tracks how default_rate was populated on insert:
    #   'manual'                  — set by admin via the rates UI
    #   'imported'                — rate came directly from the import file
    #   'inherited_from_sibling'  — $0 insert avoided; rate copied from a letter-suffix or
    #                               numbered-neighbor sibling route (auditable, not silent)
    #   'unknown_route'           — no match and no sibling found; rate defaulted to $0
    #                               (needs manual pricing in the rates page)
    # NULL on rows created before this column existed (pre-migration rows).
    default_rate_source = Column(Text, nullable=True)

    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))

    overrides = relationship("ZRateOverride", back_populates="service", cascade="all, delete-orphan")

    __table_args__ = (
        Index("uq_z_rate_service_scope", "source", "company_name", "service_name", unique=True),
        Index("ix_z_rate_service_name", "service_name"),
    )


class ZRateOverride(Base):
    __tablename__ = "z_rate_override"

    z_rate_override_id = Column(Integer, primary_key=True)
    z_rate_service_id = Column(Integer, ForeignKey("z_rate_service.z_rate_service_id", ondelete="CASCADE"), nullable=False)

    effective_during = Column(DATERANGE, nullable=False)
    override_rate = Column(Numeric(12, 2), nullable=False)
    active = Column(Boolean, nullable=False, server_default=text("true"))

    reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))

    service = relationship("ZRateService", back_populates="overrides")


class DriverBalance(Base):
    """Carried-over balance per driver per batch.

    Disposition states:
      1. Paid via Paychex   — settled_externally=False, carried_over=0
      2. Withheld           — settled_externally=False, carried_over>0
      3. Paid Externally    — settled_externally=True,  carried_over=0
    """
    __tablename__ = "driver_balance"

    driver_balance_id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    carried_over = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    updated_at = Column(DateTime(timezone=True), server_default=text("NOW()"))

    # Paid-externally disposition (Zelle, cash, retained, custom)
    settled_externally = Column(Boolean, nullable=False, server_default=text("FALSE"))
    external_method = Column(Text, nullable=True)       # 'zelle' | 'cash' | 'retained' | 'custom'
    external_amount = Column(Numeric(10, 2), nullable=True)
    external_note = Column(Text, nullable=True)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    settled_by = Column(Text, nullable=True)

    __table_args__ = (
        Index("uq_driver_balance_person_batch", "person_id", "payroll_batch_id", unique=True),
    )


class DispatchAssignment(Base):
    """Confirmed dispatch assignments — logged when a user selects a driver."""
    __tablename__ = "dispatch_assignment"

    assignment_id  = Column(Integer, primary_key=True)
    assigned_date  = Column(Date, nullable=False)
    pickup_address = Column(Text, nullable=False)
    dropoff_address = Column(Text, nullable=False)
    pickup_time    = Column(Text, nullable=False)
    dropoff_time   = Column(Text, nullable=False)
    person_id      = Column(Integer, ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False)
    source         = Column(Text, nullable=False)   # "firstalt" | "everdriven"
    notes          = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("ix_dispatch_assignment_date", "assigned_date"),
        Index("ix_dispatch_assignment_person", "person_id"),
    )


class Ride(Base):
    __tablename__ = "ride"

    ride_id = Column(BigInteger, primary_key=True)

    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False)

 
    ride_start_ts = Column(DateTime(timezone=True), nullable=True)

    service_ref = Column(Text)
    service_ref_type = Column(Text)
    service_name = Column(Text)

    source = Column(Text, nullable=False) 
    z_rate = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    z_rate_source = Column(Text, nullable=False, server_default=text("'default'"))

    z_rate_service_id = Column(Integer, ForeignKey("z_rate_service.z_rate_service_id", ondelete="SET NULL"))
    z_rate_override_id = Column(Integer, ForeignKey("z_rate_override.z_rate_override_id", ondelete="SET NULL"))

    miles = Column(Numeric(10, 3), nullable=False, server_default=text("0"))
    gross_pay = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    net_pay = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    deduction = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    spiff = Column(Numeric(12, 2), nullable=False, server_default=text("0"))

    source_ref = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    # Soft-delete — admin can remove a ride from driver payout without deleting the row.
    # Revenue (gross_pay / net_pay) is preserved; only z_rate is excluded from payout sums.
    # A ride is "removed" when removed_at IS NOT NULL.
    removed_at = Column(DateTime(timezone=True), nullable=True)
    removed_by = Column(Text, nullable=True)
    removed_reason = Column(Text, nullable=True)

    person = relationship("Person", back_populates="rides")
    batch = relationship("PayrollBatch", back_populates="rides")

    __table_args__ = (
        Index("uq_ride_source_ref", "source_ref", unique=True),
        Index("ix_ride_batch_person", "payroll_batch_id", "person_id"),
        Index("ix_ride_person_date", "person_id", "ride_start_ts"),
        Index("ix_ride_service_name", "service_name"),
        Index("ix_ride_z_rate_ids", "z_rate_service_id", "z_rate_override_id"),
    )


class EmailSendLog(Base):
    """Tracks when paystub emails were sent."""
    __tablename__ = "email_send_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    status = Column(Text, nullable=False, server_default=text("'sent'"))  # sent, failed, pending
    error_message = Column(Text, nullable=True)
    is_test = Column(Boolean, nullable=False, server_default=text("false"))


class EmailTemplate(Base):
    """Stores paystub email subject + body templates.

    Scope priority (most specific wins):
        person-level  → scope="person",  person_id=X,  payroll_batch_id=NULL
        batch-level   → scope="batch",   person_id=NULL, payroll_batch_id=X
        default       → scope="default", person_id=NULL, payroll_batch_id=NULL

    Placeholders available in subject and body:
        {{driver_name}}, {{first_name}}, {{week_start}}, {{week_end}},
        {{total_pay}}, {{company_name}}, {{ride_count}}
    """
    __tablename__ = "email_template"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(Text, nullable=False, server_default=text("'default'"))
    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=True)
    subject = Column(Text, nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False, server_default=text("'Unknown'"))
    user_color = Column(Text, nullable=True)
    action = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    entity_type = Column(Text, nullable=True)
    entity_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_activity_log_created", "created_at"),
        Index("ix_activity_log_username", "username"),
    )


class TripNotification(Base):
    """Tracks the notification lifecycle for each trip — accept and start stages."""
    __tablename__ = "trip_notification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    trip_date = Column(Date, nullable=False)
    source = Column(Text, nullable=False)       # "firstalt" | "everdriven"
    trip_ref = Column(Text, nullable=False)      # tripId (FA) or keyValue (ED)
    trip_status = Column(Text, nullable=True)    # latest raw status from API
    pickup_time = Column(Text, nullable=True)    # firstPickUp time string

    # Accept stage
    accept_sms_at = Column(DateTime(timezone=True), nullable=True)
    accept_call_at = Column(DateTime(timezone=True), nullable=True)
    accept_escalated_at = Column(DateTime(timezone=True), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    # Start stage
    start_sms_at = Column(DateTime(timezone=True), nullable=True)
    start_call_at = Column(DateTime(timezone=True), nullable=True)
    start_escalated_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)

    # Overdue alert stage
    overdue_alerted_at = Column(DateTime(timezone=True), nullable=True)

    # Backwards-reschedule guard (added via add_original_pickup_dt migration).
    # Set once when accept_sms_at is first written. If pickup_dt later moves
    # EARLIER than this value, we suppress SMS re-fire to avoid double-texting.
    original_pickup_dt = Column(DateTime(timezone=True), nullable=True)

    # Scorecard-derived timestamps (populated by trip_monitor transition detection).
    arrived_at_pickup = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Scheduled dropoff time — populated from the partner API at upsert time.
    # EverDriven: lastDropoff.dueTimeTLT (local-time string, same shape as
    #   firstPickup); parsed and stored as UTC once on first write.
    # FirstAlt: not provided — remains NULL for all FA trips.
    # Used by the on_time_completion scorecard axis.  Written once; never
    # overwritten (dispatch schedule is fixed at run-creation time).
    scheduled_dropoff = Column(DateTime(timezone=True), nullable=True)

    # Phase 2 — operator override fields
    # snoozed_until: monitor skips all re-escalation while now < snoozed_until
    snoozed_until = Column(DateTime(timezone=True), nullable=True)
    # manually_resolved_at: operator "Got it" — stops all further escalation permanently
    manually_resolved_at = Column(DateTime(timezone=True), nullable=True)
    # person_id of the operator who resolved it (nullable for backwards compat)
    manually_resolved_by = Column(Integer, nullable=True)
    # last_escalated_at: bumped each time stuck-trip re-escalation fires
    last_escalated_at = Column(DateTime(timezone=True), nullable=True)
    # Cross-source dedup: True when this notif was suppressed in favour of another
    dedup_suppressed = Column(Boolean, nullable=False, server_default=text("false"))
    # Points to the canonical (kept) notification when dedup_suppressed=true
    dedup_primary_notif_id = Column(Integer, nullable=True)

    # Phase 3 — dispatch severity tier assigned when the alert fired.
    # Values: critical | urgent | normal | silent.  Default: normal.
    dispatch_severity = Column(Text, nullable=False, server_default="normal")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("uq_trip_notification_ref", "source", "trip_ref", "trip_date", unique=True),
        Index("ix_trip_notification_date", "trip_date"),
        Index("ix_trip_notification_person", "person_id"),
    )


class TripStatusEvent(Base):
    """Append-only log of partner-status transitions detected by the polling loop.

    One row per poll cycle that observes a classified-status change on a trip.
    Key derived timestamps (accepted_at, started_at, arrived_at_pickup, completed_at)
    are inferred from the first row with the matching new_status value.
    """
    __tablename__ = "trip_status_event"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trip_notification_id = Column(
        Integer,
        ForeignKey("trip_notification.id", ondelete="CASCADE"),
        nullable=False,
    )
    source = Column(Text, nullable=False)           # 'firstalt' | 'everdriven'
    trip_ref = Column(Text, nullable=False)
    person_id = Column(
        Integer,
        ForeignKey("person.person_id", ondelete="SET NULL"),
        nullable=True,
    )
    prev_status = Column(Text, nullable=True)       # classified status before transition
    new_status = Column(Text, nullable=False)       # classified status after transition
    detected_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    poll_interval_seconds = Column(Integer, nullable=True)  # staleness bound in seconds
    raw_partner_status = Column(Text, nullable=True)        # raw API value for debugging

    trip_notification = relationship("TripNotification", foreign_keys=[trip_notification_id])
    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("ix_trip_status_event_person_detected", "person_id", "detected_at"),
        Index("ix_trip_status_event_trip", "trip_notification_id", "detected_at"),
    )


class NotificationEvent(Base):
    """Immutable audit log — one row per alert action.

    Every significant action taken by the trip monitor or by an operator
    writes a row here. Events are never deleted or modified.

    event_type values (not an enum — validated at app layer for flexibility):
        accept_sms, accept_call, accept_escalated,
        start_sms, start_call, start_escalated,
        overdue_alert, sms_sent, sms_delivered, sms_failed,
        whatsapp_sent, whatsapp_delivered, whatsapp_failed,
        voice_call_admin, snoozed, unmuted, manually_resolved,
        auto_escalated, stuck_trip_alert, mute, dedup_suppressed, reescalated
    """
    __tablename__ = "notification_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trip_notification_id = Column(
        Integer,
        ForeignKey("trip_notification.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type = Column(Text, nullable=False)
    payload = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    # The operator who triggered the event (null for automated monitor actions)
    created_by_person_id = Column(Integer, nullable=True)

    trip_notification = relationship("TripNotification", foreign_keys=[trip_notification_id])

    __table_args__ = (
        Index("ix_notification_event_notif", "trip_notification_id"),
        Index("ix_notification_event_type", "event_type"),
        Index("ix_notification_event_created", "created_at"),
    )


# DEPRECATED — drop in next migration PR. No UI entry points remain after 2026-05-01 cleanup. Confirm dispatch agent doesn't need these before dropping.

class DriverPromise(Base):
    """Tracks promises made to drivers — 'next available ride is yours'."""
    __tablename__ = "driver_promise"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    description = Column(Text, nullable=False)
    promised_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)
    fulfilled_ride_ref = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("ix_driver_promise_person", "person_id"),
    )


# DEPRECATED — drop in next migration PR. No UI entry points remain after 2026-05-01 cleanup. Confirmed: dispatch agent does NOT read from this table.
class DriverBlackout(Base):
    """Marks a driver as unavailable for a date range."""
    __tablename__ = "driver_blackout"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    reason = Column(Text, nullable=True)
    recurring = Column(Boolean, nullable=False, server_default=text("false"))
    recurring_days = Column(JSON, nullable=True)  # list of weekday ints [0..6]
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("ix_driver_blackout_person", "person_id"),
        Index("ix_driver_blackout_dates", "start_date", "end_date"),
    )


class PaychexSession(Base):
    """Stores captured Paychex browser session cookies per company."""
    __tablename__ = "paychex_sessions"

    company = Column(String(20), primary_key=True)        # "acumen" or "maz"
    cookies = Column(JSON, nullable=False)                 # list of cookie dicts (native JSON)
    captured_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class BatchWorkflowLog(Base):
    """Tracks every stage transition for a payroll batch."""
    __tablename__ = "batch_workflow_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    from_status = Column(Text, nullable=True)  # null for initial creation
    to_status = Column(Text, nullable=False)
    triggered_by = Column(Text, nullable=False, server_default=text("'system'"))
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    batch = relationship("PayrollBatch", back_populates="workflow_logs")

    __table_args__ = (
        Index("ix_batch_workflow_log_batch", "payroll_batch_id"),
    )


class BatchCorrectionLog(Base):
    """Audit trail for manual corrections made to a payroll batch."""
    __tablename__ = "batch_correction_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="SET NULL"), nullable=True)
    field = Column(Text, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    corrected_by = Column(Text, nullable=False, server_default=text("'user'"))
    corrected_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_batch_correction_batch", "batch_id"),
        Index("ix_batch_correction_person", "person_id"),
    )


# DEPRECATED — drop in next migration PR. /dispatch/manage removed 2026-05-01 cleanup.
class DispatchSessionLog(Base):
    """Read-only history of dispatch planning sessions. Never affects live dispatch data."""
    __tablename__ = "dispatch_session_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_date = Column(Date, nullable=False)
    changes_json = Column(Text, nullable=False)  # JSON array of SessionChange objects
    change_count = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_dispatch_session_log_date", "session_date"),
    )


class OnboardingRecord(Base):
    """Tracks a driver's onboarding progress end-to-end."""
    __tablename__ = "onboarding_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False, unique=True)
    # step statuses: "pending" | "sent" | "signed" | "complete" | "manual" | "skipped"
    consent_status = Column(Text, nullable=False, server_default=text("'pending'"))  # drug test consent form
    consent_envelope_id = Column(Text, nullable=True)      # Adobe Sign envelope ID
    priority_email_status = Column(Text, nullable=False, server_default=text("'pending'"))  # repurposed: FirstAlt invite status
    brandon_email_status = Column(Text, nullable=False, server_default=text("'pending'"))   # manual 1-click
    bgc_status = Column(Text, nullable=False, server_default=text("'pending'"))             # monitor auto-detects; manual override allowed
    drug_test_status = Column(Text, nullable=False, server_default=text("'pending'"))       # monitor auto-detects; manual override allowed
    contract_status = Column(Text, nullable=False, server_default=text("'pending'"))
    contract_envelope_id = Column(Text, nullable=True)     # Adobe Sign envelope ID
    files_status = Column(Text, nullable=False, server_default=text("'pending'"))           # DL + reg + inspection
    paychex_status = Column(Text, nullable=False, server_default=text("'pending'"))
    training_status = Column(String(20), nullable=False, server_default=text("'pending'"))
    maz_training_status = Column(Text, nullable=False, server_default=text("'pending'"))
    maz_contract_status = Column(Text, nullable=False, server_default=text("'pending'"))
    notes = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    intake_submitted_at = Column(DateTime(timezone=True), nullable=True)
    # Driver self-onboarding portal
    invite_token = Column(String(64), nullable=True, unique=True, index=True)  # unique link token
    personal_info = Column(JSON, nullable=True)  # driver-submitted personal data
    # Automation
    automation_live = Column(Boolean, nullable=False, server_default=text("false"))
    automation_log = Column(JSON, nullable=True)   # list of {step, action, description, executed_at, dry_run}
    maz_contract_signed_name = Column(Text, nullable=True)
    maz_contract_signed_at = Column(DateTime(timezone=True), nullable=True)
    # EverDriven onboarding fields
    partner = Column(String(20), nullable=False, server_default=text("'firstalt'"))
    cc_id = Column(String(100), nullable=True)
    cc_status = Column(JSON, nullable=True)
    hallo_link_sent_at = Column(DateTime(timezone=True), nullable=True)
    hallo_score = Column(Numeric(4, 1), nullable=True)
    hallo_completed_at = Column(DateTime(timezone=True), nullable=True)
    saferide_link_sent_at = Column(DateTime(timezone=True), nullable=True)
    saferide_cert_uploaded_at = Column(DateTime(timezone=True), nullable=True)
    ed_app_install_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    equipment_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    ed_vehicle_insp_1_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    ed_vehicle_insp_2_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    ed_bgc_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    ed_drug_test_status = Column(String(20), nullable=True, server_default=text("'pending'"))
    # Drug test consent tracking (moved from person table)
    drug_test_agreement_id = Column(Text, nullable=True)
    drug_test_sent_at = Column(DateTime(timezone=True), nullable=True)
    drug_test_signed_at = Column(DateTime(timezone=True), nullable=True)
    # First Advantage BGC fields (FA onboarding — migration aa2b3c4d5e6f)
    fadv_report_id = Column(Text, nullable=True)
    fadv_status = Column(Text, nullable=True)          # pending | initiated | clear | consider | suspended
    fadv_initiated_at = Column(DateTime(timezone=True), nullable=True)
    fadv_result_at = Column(DateTime(timezone=True), nullable=True)
    fadv_raw = Column(JSON, nullable=True)              # raw FADV API response for audit
    # Contractor Compliance invite tracking (ED step 1)
    cc_invite_sent_at = Column(DateTime(timezone=True), nullable=True)

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("ix_onboarding_record_person", "person_id"),
    )


class OnboardingDocument(Base):
    """Adobe Sign envelope tracking for consent forms and contracts."""
    __tablename__ = "onboarding_document"

    id = Column(Integer, primary_key=True, autoincrement=True)
    onboarding_id = Column(Integer, ForeignKey("onboarding_record.id", ondelete="CASCADE"), nullable=False)
    doc_type = Column(Text, nullable=False)   # "consent_form" | "acumen_contract"
    envelope_id = Column(Text, nullable=True)
    status = Column(Text, nullable=False, server_default=text("'pending'"))  # pending | sent | signed | expired
    sent_at = Column(DateTime(timezone=True), nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)
    signer_email = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_onboarding_document_onboarding", "onboarding_id"),
        Index("uq_onboarding_document_envelope", "envelope_id", unique=True),
    )


class OnboardingFile(Base):
    """Driver document files stored in Cloudflare R2."""
    __tablename__ = "onboarding_file"

    id = Column(Integer, primary_key=True, autoincrement=True)
    onboarding_id = Column(Integer, ForeignKey("onboarding_record.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(Text, nullable=False)   # "drivers_license" | "vehicle_registration" | "inspection"
    r2_key = Column(Text, nullable=True)       # R2 object key
    r2_url = Column(Text, nullable=True)       # public or presigned URL
    filename = Column(Text, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)   # for DL and inspection renewals

    __table_args__ = (
        Index("ix_onboarding_file_onboarding", "onboarding_id"),
    )


class OpsNote(Base):
    """Shared ops notes between Malik and Mom — command center sticky notes."""
    __tablename__ = "ops_notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    body = Column(Text, nullable=False)
    created_by = Column(Text, nullable=False)   # "Malik" | "Mom"
    done = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    done_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_ops_notes_created_at", "created_at"),
    )


class UserAccount(Base):
    """
    Team member account — Malik, Mom, and future hires (Associates).

    Roles:
      admin     — full access (Malik)
      operator  — full access minus things admin flags 'admin only' (Mom)
      associate — only their scoped views + assigned tasks (new hires)

    Password hashes are bcrypt; auth middleware validates via bcrypt.checkpw.
    """
    __tablename__ = "user_account"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(Text, nullable=False, unique=True)
    full_name = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    role = Column(Text, nullable=False, server_default=text("'associate'"))
    password_hash = Column(Text, nullable=False, server_default=text("''"))
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    language = Column(Text, nullable=False, server_default=text("'en'"))
    color = Column(Text, nullable=False, server_default=text("'#4facfe'"))
    initials = Column(Text, nullable=False, server_default=text("'?'"))
    avatar_url = Column(Text, nullable=True)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_user_account_username", "username", unique=True),
        Index("ix_user_account_role", "role"),
    )

    def to_safe_dict(self) -> dict:
        """Serialize for session cookie / API response — omits password_hash."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "full_name": self.full_name,
            "display_name": self.display_name,
            "role": self.role,
            "email": self.email,
            "phone": self.phone,
            "language": self.language,
            "color": self.color,
            "initials": self.initials,
            "avatar_url": self.avatar_url,
            "active": self.active,
        }


# ── Team OS Phase 2: SOPs + Tasks ── DEPRECATED — drop tables in next migration PR (2026-05-01 walk-through cleanup) ──

class SOP(Base):
    """Standard Operating Procedure — how-to docs for the team."""
    __tablename__ = "sop"

    sop_id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    category = Column(Text, nullable=True)          # 'payroll' | 'dispatch' | 'onboarding' | 'admin' | ...
    owner_role = Column(Text, nullable=False, server_default=text("'operator'"))
    trigger_when = Column(Text, nullable=True)      # human-readable "when to use this"
    content = Column(Text, nullable=False)          # markdown body
    version = Column(Integer, nullable=False, server_default=text("1"))
    created_by = Column(Integer, ForeignKey("user_account.user_id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user_account.user_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    archived = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index("ix_sop_category", "category"),
        Index("ix_sop_archived", "archived"),
    )

    def to_dict(self) -> dict:
        return {
            "sop_id": self.sop_id,
            "title": self.title,
            "category": self.category,
            "owner_role": self.owner_role,
            "trigger_when": self.trigger_when,
            "content": self.content,
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "archived": self.archived,
        }


class SOPFieldNote(Base):
    """Notes from the field — any user can annotate an SOP."""
    __tablename__ = "sop_field_note"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sop_id = Column(Integer, ForeignKey("sop.sop_id", ondelete="CASCADE"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("user_account.user_id"), nullable=False)
    note = Column(Text, nullable=False)
    promoted = Column(Boolean, nullable=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_sop_field_note_sop", "sop_id"),
    )


# DEPRECATED — drop in next migration PR (2026-05-01 walk-through cleanup).
class Task(Base):
    """Delegable work item — assigned to a team member."""
    __tablename__ = "task"

    task_id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    assignee_id = Column(Integer, ForeignKey("user_account.user_id"), nullable=True)
    created_by = Column(Integer, ForeignKey("user_account.user_id"), nullable=True)
    priority = Column(Text, nullable=False, server_default=text("'normal'"))   # low | normal | high | urgent
    status = Column(Text, nullable=False, server_default=text("'todo'"))       # todo | in_progress | blocked | done
    due_at = Column(DateTime(timezone=True), nullable=True)
    linked_sop_id = Column(Integer, ForeignKey("sop.sop_id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_task_assignee", "assignee_id"),
        Index("ix_task_status", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "description": self.description,
            "assignee_id": self.assignee_id,
            "created_by": self.created_by,
            "priority": self.priority,
            "status": self.status,
            "due_at": self.due_at.isoformat() if self.due_at else None,
            "linked_sop_id": self.linked_sop_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class TaskChecklistItem(Base):
    __tablename__ = "task_checklist_item"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("task.task_id", ondelete="CASCADE"), nullable=False)
    label = Column(Text, nullable=False)
    done = Column(Boolean, nullable=False, server_default=text("false"))
    order_index = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("ix_task_checklist_task", "task_id"),
    )


class TaskComment(Base):
    __tablename__ = "task_comment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Integer, ForeignKey("task.task_id", ondelete="CASCADE"), nullable=False)
    author_user_id = Column(Integer, ForeignKey("user_account.user_id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    __table_args__ = (
        Index("ix_task_comment_task", "task_id"),
    )


class AppConfig(Base):
    __tablename__ = "app_config"

    key   = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"), onupdate=text("NOW()"))


class ScorecardCronRun(Base):
    """Idempotency log for the weekly scorecard SMS/email cron.

    One row per (week_iso, person_id). The UNIQUE constraint prevents
    double-sends when the cron fires more than once in the same week
    or when the manual /admin/scorecard/send-now endpoint is triggered
    while a Sunday run is already in progress.
    """
    __tablename__ = "scorecard_cron_run"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    person_id  = Column(
        Integer,
        ForeignKey("person.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    week_iso   = Column(Text, nullable=False)
    sent_at    = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    sms_sent   = Column(Boolean, nullable=False, server_default=text("false"))
    email_sent = Column(Boolean, nullable=False, server_default=text("false"))
    sms_error  = Column(Text, nullable=True)
    email_error = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_scorecard_cron_run_person_week", "person_id", "week_iso"),
        {"extend_existing": True},
    )


class ScorecardCache(Base):
    """Weekly per-driver scorecard snapshot written by the Sunday cron.

    One row per (person_id, week_num, year). Enables:
    - Week-over-week delta computation without re-running the full pipeline
    - 30-day rolling average view on /dispatch/reliability
    - Public driver scorecard trend sparkline

    source: 'cron' (Sunday auto-run) or 'manual' (send-now trigger).
    """
    __tablename__ = "scorecard_cache"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    person_id        = Column(
        Integer,
        ForeignKey("person.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    week_num         = Column(Integer, nullable=False)
    year             = Column(Integer, nullable=False)
    week_iso         = Column(Text, nullable=False)
    self_serve_pct   = Column(Numeric(6, 2), nullable=True)
    on_time_pct      = Column(Numeric(6, 2), nullable=True)
    escalation_count = Column(Integer, nullable=True)
    composite_score  = Column(Numeric(7, 4), nullable=True)
    total_trips      = Column(Integer, nullable=False, server_default=text("0"))
    computed_at      = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    source           = Column(String(16), nullable=False, server_default=text("'cron'"))

    __table_args__ = (
        Index("ix_scorecard_cache_person_id", "person_id"),
        Index("ix_scorecard_cache_week", "year", "week_num"),
        {"extend_existing": True},
    )


class AuditLog(Base):
    """
    Immutable server-side audit trail for sensitive mutations.

    Every row captures who did what to which record, the before/after state,
    and the HTTP context (ip + user_agent) so accidental or malicious changes
    are always traceable.

    actor_user_id / actor_email may be NULL for system-initiated actions
    (e.g. cron jobs, migration scripts).
    """
    __tablename__ = "audit_log"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id  = Column(Integer, ForeignKey("user_account.user_id", ondelete="SET NULL"), nullable=True)
    actor_email    = Column(Text, nullable=True)
    action         = Column(Text, nullable=False)          # e.g. "person.toggle_active"
    target_type    = Column(Text, nullable=False)          # e.g. "person"
    target_id      = Column(Integer, nullable=False)
    before_value   = Column(JSON, nullable=True)
    after_value    = Column(JSON, nullable=True)
    ip             = Column(Text, nullable=True)
    user_agent     = Column(Text, nullable=True)
    created_at     = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )

    __table_args__ = (
        Index("ix_audit_log_action", "action"),
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_actor", "actor_user_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )


class PaystubArchive(Base):
    """
    Permanent store of every pay stub PDF ever generated by Z-Pay.

    One canonical row per (person_id, payroll_batch_id).
    The service layer is idempotent — regenerating or re-sending a stub
    updates the existing row in-place rather than accumulating duplicates.

    Fields
    ------
    file_path           Relative path from DATA_DIR root, e.g.
                        "paystubs/{batch_id}/{person_id}.pdf".
                        Absolute path = DATA_DIR / file_path.
    regenerated_from_data
                        False  → original PDF captured at send time.
                        True   → PDF was rebuilt from current ride data
                                 (useful after rate corrections).
    sent_at             NULL if the stub was generated for preview only
                        and never emailed.
    """
    __tablename__ = "paystub_archive"

    paystub_id            = Column(Integer, primary_key=True, autoincrement=True)
    person_id             = Column(
        Integer,
        ForeignKey("person.person_id", ondelete="CASCADE"),
        nullable=False,
    )
    payroll_batch_id      = Column(
        Integer,
        ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"),
        nullable=False,
    )
    generated_at          = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("NOW()"),
    )
    sent_at               = Column(DateTime(timezone=True), nullable=True)
    recipient_email       = Column(Text, nullable=True)
    file_path             = Column(Text, nullable=False)
    file_size_bytes       = Column(Integer, nullable=True)
    total_pay             = Column(Numeric(12, 2), nullable=True)
    ride_count            = Column(Integer, nullable=True)
    regenerated_from_data = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )

    person = relationship("Person")
    batch  = relationship("PayrollBatch")

    __table_args__ = (
        # Unique constraint: one canonical row per driver+batch
        Index(
            "uq_paystub_archive_person_batch",
            "person_id",
            "payroll_batch_id",
            unique=True,
        ),
        # Per-driver list ordered by most recent first
        Index("ix_paystub_archive_person_generated", "person_id", "generated_at"),
        # Batch-wise lookups (resend-all, backfill progress)
        Index("ix_paystub_archive_batch", "payroll_batch_id"),
    )

from sqlalchemy import (
    Column, Integer, BigInteger, Text, Boolean, Date, DateTime, ForeignKey, Numeric,
    Index, text, String, JSON
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
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))
    notes = Column(Text, nullable=True)
    language = Column(String(20), nullable=True)  # "en", "ar", "am" — preferred language for automated calls
    vehicle_make = Column(Text, nullable=True)
    vehicle_model = Column(Text, nullable=True)
    vehicle_year = Column(Integer, nullable=True)
    vehicle_plate = Column(Text, nullable=True)
    vehicle_color = Column(Text, nullable=True)
    # tin and license_number REMOVED — contained SSN data, wiped for security

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
    """Manually-entered carried-over balance per driver per batch."""
    __tablename__ = "driver_balance"

    driver_balance_id = Column(Integer, primary_key=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False)
    payroll_batch_id = Column(Integer, ForeignKey("payroll_batch.payroll_batch_id", ondelete="CASCADE"), nullable=False)
    carried_over = Column(Numeric(12, 2), nullable=False, server_default=text("0"))
    updated_at = Column(DateTime(timezone=True), server_default=text("NOW()"))

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

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))

    person = relationship("Person", foreign_keys=[person_id])

    __table_args__ = (
        Index("uq_trip_notification_ref", "source", "trip_ref", "trip_date", unique=True),
        Index("ix_trip_notification_date", "trip_date"),
        Index("ix_trip_notification_person", "person_id"),
    )


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


class OnboardingRecord(Base):
    """Tracks a driver's onboarding progress end-to-end."""
    __tablename__ = "onboarding_record"

    id = Column(Integer, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=False, unique=True)
    # step statuses: "pending" | "sent" | "signed" | "complete" | "manual" | "skipped"
    consent_status = Column(Text, nullable=False, server_default=text("'pending'"))
    consent_envelope_id = Column(Text, nullable=True)      # Adobe Sign envelope ID
    priority_email_status = Column(Text, nullable=False, server_default=text("'pending'"))  # auto-sent after consent signed
    brandon_email_status = Column(Text, nullable=False, server_default=text("'pending'"))   # manual 1-click
    bgc_status = Column(Text, nullable=False, server_default=text("'pending'"))             # monitor auto-detects; manual override allowed
    drug_test_status = Column(Text, nullable=False, server_default=text("'pending'"))       # monitor auto-detects; manual override allowed
    contract_status = Column(Text, nullable=False, server_default=text("'pending'"))
    contract_envelope_id = Column(Text, nullable=True)     # Adobe Sign envelope ID
    files_status = Column(Text, nullable=False, server_default=text("'pending'"))           # DL + reg + inspection
    paychex_status = Column(Text, nullable=False, server_default=text("'pending'"))
    training_status = Column(String(20), nullable=False, server_default=text("'pending'"))
    notes = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    # Driver self-onboarding portal
    invite_token = Column(String(64), nullable=True, unique=True, index=True)  # unique link token
    personal_info = Column(JSON, nullable=True)  # driver-submitted personal data

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

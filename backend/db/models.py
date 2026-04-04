from sqlalchemy import (
    Column, Integer, BigInteger, Text, Boolean, Date, DateTime, ForeignKey, Numeric,
    Index, text, String
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import DATERANGE

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
    vehicle_make = Column(Text, nullable=True)
    vehicle_model = Column(Text, nullable=True)
    vehicle_year = Column(Integer, nullable=True)
    vehicle_plate = Column(Text, nullable=True)
    vehicle_color = Column(Text, nullable=True)
    tin = Column(Text, nullable=True)
    license_number = Column(Text, nullable=True)

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

    rides = relationship("Ride", back_populates="batch")


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

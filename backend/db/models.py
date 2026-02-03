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
    active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), server_default=text("NOW()"))

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

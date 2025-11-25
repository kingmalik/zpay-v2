from __future__ import annotations
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column
from sqlalchemy import Integer, BigInteger, String, Text, Boolean, DateTime, Date, ForeignKey, Numeric
from datetime import datetime, timezone

Base = declarative_base()

class Person(Base):
    __tablename__ = "person"
    person_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    rides: Mapped[list["Ride"]] = relationship(back_populates="person", cascade="all,delete-orphan")

class CommissionRule(Base):
    __tablename__ = "commission_rule"
    rule_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("person.person_id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="finder_fee")
    pct_fee: Mapped[float] = mapped_column(Numeric(6,4), nullable=False)
    effective_from: Mapped[Date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[Date | None] = mapped_column(Date)

class Ride(Base):
    __tablename__ = "ride"
    ride_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(Integer, ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False)
    ride_start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ride_end_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    origin: Mapped[str | None] = mapped_column(Text)
    destination: Mapped[str | None] = mapped_column(Text)
    distance_km: Mapped[float | None] = mapped_column(Numeric(10,3))
    duration_min: Mapped[float | None] = mapped_column(Numeric(10,2))
    base_fare: Mapped[float] = mapped_column(Numeric(12,2), nullable=False, default=0)
    tips: Mapped[float] = mapped_column(Numeric(12,2), nullable=False, default=0)
    adjustments: Mapped[float] = mapped_column(Numeric(12,2), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(Text, nullable=False, default="USD")
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    person: Mapped["Person"] = relationship(back_populates="rides")

from sqlalchemy import Column, Integer, BigInteger, String, Boolean, Numeric, Text, ForeignKey, TIMESTAMP, func
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class Person(Base):
    __tablename__ = "person"

    person_id = Column(Integer, primary_key=True, autoincrement=True)
    external_id = Column(String, unique=True, index=True)
    full_name = Column(String)
    email = Column(String)
    phone = Column(String)
    active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    rides = relationship("Ride", back_populates="person")


class Ride(Base):
    __tablename__ = "ride"

    ride_id = Column(BigInteger, primary_key=True, autoincrement=True)
    person_id = Column(Integer, ForeignKey("person.person_id", ondelete="RESTRICT"), nullable=False)
    ride_start_ts = Column(TIMESTAMP(timezone=True), nullable=False)
    ride_end_ts = Column(TIMESTAMP(timezone=True))
    origin = Column(Text)
    destination = Column(Text)
    distance_km = Column(Numeric(10, 3))
    duration_min = Column(Numeric(10, 2))
    base_fare = Column(Numeric(12, 2), nullable=False, default=0)
    tips = Column(Numeric(12, 2), nullable=False, default=0)
    adjustments = Column(Numeric(12, 2), nullable=False, default=0)
    currency = Column(Text, nullable=False, default="USD")
    source_ref = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    person = relationship("Person", back_populates="rides")

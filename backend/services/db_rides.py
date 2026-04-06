from __future__ import annotations
import pandas as pd
from sqlalchemy.orm import Session

from backend.utils.orm_introspect import person_pk_attr, ride_fk_to_person_attr

def insert_ride_from_row(db: Session, Ride, person_obj, row: dict) -> None:
    """Create a Ride from a normalized row dict, linking to person_obj."""
    pk_name = person_pk_attr(type(person_obj))
    ride_fk_name = ride_fk_to_person_attr(type(person_obj), Ride)

    ride_kwargs = {
        "external_id": str(row.get("external_id") or ""),
        "ride_start_ts": row.get("ride_start_ts"),
        "base_fare": float(row.get("base_fare") or 0),
        "distance_miles": float(row.get("distance_miles") or 0) if pd.notna(row.get("distance_miles")) else None,
        "net_pay": float(row.get("net_pay") or 0) if pd.notna(row.get("net_pay")) else None,
        # Optional mirrors if your Ride model has them:
        "driver_code": (row.get("code") or None),
        "driver_name": (row.get("person") or None),
        "route_name": (row.get("name") or None),
    }

    # keep only attributes that exist on Ride
    ride_kwargs = {k: v for k, v in ride_kwargs.items() if hasattr(Ride, k)}

    # link to Person
    if ride_fk_name and hasattr(Ride, ride_fk_name):
        ride_kwargs[ride_fk_name] = getattr(person_obj, pk_name)
    elif hasattr(Ride, "person_id"):
        ride_kwargs["person_id"] = getattr(person_obj, pk_name)

    db.add(Ride(**ride_kwargs))

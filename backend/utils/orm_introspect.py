from __future__ import annotations
from typing import Optional, Tuple
from sqlalchemy import inspect as sa_inspect

def person_pk_attr(Person) -> str:
    return sa_inspect(Person).primary_key[0].key

def ride_pk_attr(Ride) -> str:
    return sa_inspect(Ride).primary_key[0].key

def ride_fk_to_person_attr(Person, Ride) -> Optional[str]:
    person_table = sa_inspect(Person).local_table
    for col in sa_inspect(Ride).columns:
        for fk in col.foreign_keys:
            if fk.column.table.name == person_table.name:
                return col.key
    return None

def person_name_fields(Person) -> Tuple[Optional[str], Optional[str]]:
    """Return ('code_field', 'name_field') that exist on Person, if any."""
    code_field = "code" if hasattr(Person, "code") else None
    if hasattr(Person, "full_name"):
        name_field = "full_name"
    elif hasattr(Person, "name"):
        name_field = "name"
    else:
        name_field = None
    return code_field, name_field

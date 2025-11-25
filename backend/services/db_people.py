from __future__ import annotations
from typing import Dict, Iterable
from sqlalchemy import select
from sqlalchemy.orm import Session

# Include 'external' because your Person table uses it for the code.
CODE_FIELDS: tuple[str, ...] = ("code", "employee_code", "driver_code", "external")
NAME_FIELDS: tuple[str, ...] = ("name", "full_name", "display_name")

def _get_any_attr(obj, candidates: Iterable[str]):
    for c in candidates:
        if hasattr(obj, c):
            return getattr(obj, c)
    return None

def _person_key(code: str | None, name: str | None) -> str:
    c = (code or "").strip()
    n = (name or "").strip()
    return f"{c}|{n}" if (c or n) else "UNKNOWN|"

def build_existing_people_map(db: Session, Person) -> Dict[str, object]:
    """Map (code|name) -> Person using ANY known code/name fields."""
    existing: Dict[str, object] = {}
    for p in db.execute(select(Person)).scalars().all():
        code_val = _get_any_attr(p, CODE_FIELDS)
        name_val = _get_any_attr(p, NAME_FIELDS)
        key = _person_key(code_val, name_val)
        existing[key] = p
    return existing

def get_or_create_person(
    db: Session,
    Person,
    row_code: str,
    row_name: str,
    existing_by_key: Dict[str, object] | None = None,
) -> object:
    """
    Find or insert a Person using (code|name).
    On insert, populate ANY of the supported fields that exist on the model,
    including 'external' if present.
    """
    if existing_by_key is None:
        existing_by_key = build_existing_people_map(db, Person)

    key = _person_key(row_code, row_name)
    person = existing_by_key.get(key)
    if person:
        return person

    person = Person()
    # Set every compatible code field
    for cf in CODE_FIELDS:
        if hasattr(person, cf):
            setattr(person, cf, (row_code or None))
    # Set every compatible name field
    for nf in NAME_FIELDS:
        if hasattr(person, nf):
            setattr(person, nf, (row_name or None))

    db.add(person)
    db.flush()
    existing_by_key[key] = person
    return person

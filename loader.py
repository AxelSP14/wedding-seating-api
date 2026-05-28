"""
loader.py — All database queries in one place
----------------------------------------------
This file is the only one allowed to talk to MySQL.
Every other file just calls a function here and gets back plain Python objects.

Why isolate queries here?
  - If the database schema changes, you fix it in ONE place.
  - The algorithm files (classifier, assigner) stay clean — they work with
    Python objects and never need to know SQL exists.

Think of this file as the "waiter" that goes to the kitchen (database)
and brings food (data) back to the table (algorithm).
"""

from db import get_connection
from models import Guest, Table


def load_confirmed_guests() -> list[Guest]:
    """
    Load every guest whose status is CONFIRMADO.
    These are the only guests the algorithm will seat.
    """
    sql = """
        SELECT
            id,
            name,
            last_name,
            family_id,
            parentesco,
            genero,
            is_minor,
            movilidad_reducida,
            depende_de_guest_id
        FROM guests
        WHERE status_confirmacion = 'CONFIRMADO'
        ORDER BY id
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()   # list of dicts thanks to DictCursor

    # Convert each raw dict into a typed Guest object.
    # bool(row["is_minor"]) converts MySQL's 0/1 tinyint to Python True/False.
    return [
        Guest(
            id=row["id"],
            name=row["name"],
            last_name=row["last_name"],
            family_id=row["family_id"],
            parentesco=row["parentesco"] or "DESCONOCIDO",
            genero=row["genero"] or "PENDIENTE",
            is_minor=bool(row["is_minor"]),
            movilidad_reducida=bool(row["movilidad_reducida"]) if row["movilidad_reducida"] is not None else None,
            depende_de_guest_id=row["depende_de_guest_id"],
        )
        for row in rows
    ]


def load_no_separar_de_pairs() -> list[tuple[int, int]]:
    """
    Load all (guest_id, other_guest_id) pairs from guest_no_separar_de.
    These guests MUST sit at the same table.

    The table stores both directions (A→B and B→A) so we don't need
    to add reverse pairs ourselves.
    """
    sql = "SELECT guest_id, other_guest_id FROM guest_no_separar_de"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    return [(row["guest_id"], row["other_guest_id"]) for row in rows]


def load_no_sentar_con_pairs() -> list[tuple[int, int]]:
    """
    Load all (guest_id, other_guest_id) pairs from guest_no_sentar_con.
    These guests MUST NOT sit at the same table — hard constraint.
    """
    sql = "SELECT guest_id, other_guest_id FROM guest_no_sentar_con"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    return [(row["guest_id"], row["other_guest_id"]) for row in rows]


def load_pinned_assignments() -> dict[int, int]:
    """
    Return {guest_id: table_id} for every row in table_assignments
    where pinned = 1 (manually moved by an admin).
    The algorithm treats these as pre-assigned and never overwrites them.
    """
    sql = "SELECT guest_id, table_id FROM table_assignments WHERE pinned = 1"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    return {row["guest_id"]: row["table_id"] for row in rows}


def load_tables() -> list[Table]:
    """
    Load all tables from tables_event.
    The 'notes' column is checked later to identify accessible tables
    (we look for the word 'accesible' in the notes text).
    """
    sql = "SELECT id, table_name, capacity, notes FROM tables_event ORDER BY id"
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
    return [
        Table(
            id=row["id"],
            name=row["table_name"],
            capacity=row["capacity"],
            notes=row["notes"],
        )
        for row in rows
    ]

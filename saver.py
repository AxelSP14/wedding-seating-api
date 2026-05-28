"""
saver.py — Write assignment results back to MySQL
--------------------------------------------------
Once the algorithm finishes, we persist the results to the
'table_assignments' table that already exists in the database.

Schema reminder:
  table_assignments(
      id          BIGINT AUTO_INCREMENT PRIMARY KEY,
      guest_id    BIGINT UNIQUE,    -- one row per guest
      table_id    BIGINT,
      score       DECIMAL,          -- the score the algorithm gave this placement
      reason      VARCHAR(255)      -- human-readable explanation
  )

We use INSERT ... ON DUPLICATE KEY UPDATE so that if you run the algorithm
twice, it just updates the existing rows instead of crashing with a
"duplicate key" error.
"""

from db import get_connection
from loader import load_pinned_assignments
from models import Guest, Cluster


def save_assignments(
    assignments: dict[int, int],          # guest_id → table_id
    guests_by_id: dict[int, Guest],
    clusters_by_guest: dict[int, Cluster], # guest_id → its Cluster (for reason)
) -> None:
    """
    Persist every guest→table assignment to the database.

    We INSERT all rows in a single database round-trip using
    executemany() — much faster than calling execute() in a loop.
    """

    pinned_ids = set(load_pinned_assignments().keys())

    rows = []
    for guest_id, table_id in assignments.items():
        if guest_id in pinned_ids:
            continue  # admin-pinned assignment — never overwrite
        guest = guests_by_id[guest_id]
        cluster = clusters_by_guest.get(guest_id)

        # Build a short human-readable reason string stored alongside the result.
        # This helps you understand WHY a guest ended up at a particular table.
        reason_parts = [f"Parentesco: {guest.parentesco}"]
        if cluster:
            reason_parts.append(f"Cluster size: {cluster.size}")
        if guest.movilidad_reducida:
            reason_parts.append("Movilidad reducida")
        reason = " | ".join(reason_parts)

        rows.append((guest_id, table_id, reason))

    sql = """
        INSERT INTO table_assignments (guest_id, table_id, reason)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE
            table_id = VALUES(table_id),
            reason   = VALUES(reason)
    """

    with get_connection() as conn:
        with conn.cursor() as cursor:
            # executemany() sends all rows to MySQL in one go.
            cursor.executemany(sql, rows)
        conn.commit()   # commit() makes the changes permanent in the DB


def clear_assignments() -> None:
    """
    Delete all rows from table_assignments.
    Used by the /reset endpoint so you can start fresh.
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM table_assignments")
        conn.commit()


def load_current_assignments() -> list[dict]:
    """
    Read back the current assignments from the DB, joining guests and tables
    so the response contains human-readable names instead of raw IDs.
    """
    sql = """
        SELECT
            ta.guest_id,
            ta.table_id,
            ta.reason,
            g.name,
            g.last_name,
            g.parentesco,
            g.genero,
            g.movilidad_reducida,
            te.table_name
        FROM table_assignments ta
        JOIN guests         g  ON g.id  = ta.guest_id
        JOIN tables_event   te ON te.id = ta.table_id
        ORDER BY te.table_name, g.last_name, g.name
    """
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

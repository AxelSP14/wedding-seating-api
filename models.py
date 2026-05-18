"""
models.py — Data shapes used throughout the app
-------------------------------------------------
Python has two ways to define a data shape:

  1. @dataclass  — a plain Python object. We use these INTERNALLY inside the
                   algorithm (classifier, assigner). They're fast and simple.

  2. BaseModel   — a Pydantic model. We use these for the API RESPONSES that
                   FastAPI sends back to the caller as JSON. Pydantic validates
                   types automatically and handles the JSON conversion for us.

Think of @dataclass like a sticky note you use at your desk,
and BaseModel like an official form you hand to someone else.
"""

from dataclasses import dataclass, field
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Internal models (used by the algorithm, never sent over the network)
# ---------------------------------------------------------------------------

@dataclass
class Guest:
    """
    One confirmed guest loaded from the 'guests' table.
    We only keep the fields the algorithm actually needs.
    """
    id: int
    name: str
    last_name: str
    family_id: int
    parentesco: str          # e.g. "IGLESIA_AXEL", "FAM_VAL" …
    genero: str              # "HOMBRE" or "MUJER"
    is_minor: bool
    movilidad_reducida: Optional[bool]   # True = needs accessible seating
    depende_de_guest_id: Optional[int]   # this guest MUST sit with that guest


@dataclass
class Cluster:
    """
    A cluster is a group of guests that MUST sit at the same table.

    We build clusters by merging:
      - guests linked by depende_de_guest_id  (A depends on B → same table)
      - guests linked by no_separar_de        (A and B must not be separated)

    The algorithm treats each cluster as a single, indivisible block.
    It never splits a cluster across two tables.
    """
    guest_ids: list = field(default_factory=list)

    # Counts how many guests in this cluster belong to each parentesco group.
    # Example: {"IGLESIA_AXEL": 2, "FAM_VAL": 1}
    # We use this later to prefer putting similar groups at the same table.
    parentesco_votes: dict = field(default_factory=dict)

    # All family IDs present in this cluster (a cluster can span families).
    family_ids: set = field(default_factory=set)

    # True if at least one guest in this cluster needs accessible seating.
    has_mobility: bool = False

    @property
    def size(self) -> int:
        """How many guests are in this cluster."""
        return len(self.guest_ids)

    @property
    def dominant_parentesco(self) -> Optional[str]:
        """The parentesco group that appears most in this cluster."""
        if not self.parentesco_votes:
            return None
        return max(self.parentesco_votes, key=self.parentesco_votes.get)


@dataclass
class Table:
    """One row from the 'tables_event' table."""
    id: int
    name: str
    capacity: int            # max guests this table can hold
    notes: Optional[str]     # free text — we check for "accesible" here


# ---------------------------------------------------------------------------
# API response models (what FastAPI sends back as JSON)
# ---------------------------------------------------------------------------

class GuestSummary(BaseModel):
    """Compact guest info shown inside a table assignment response."""
    id: int
    name: str
    last_name: str
    parentesco: str
    genero: str
    movilidad_reducida: Optional[bool]


class TableResult(BaseModel):
    """
    The final assignment for one table.
    FastAPI will automatically convert this to JSON when we return it.
    """
    table_id: int
    table_name: str
    guest_count: int
    guests: list[GuestSummary]


class SeatingResult(BaseModel):
    """
    The full result of running the algorithm — one entry per table,
    plus any warnings the algorithm produced.
    """
    total_guests_assigned: int
    tables: list[TableResult]
    warnings: list[str]   # e.g. "cluster too large", "no valid table found"

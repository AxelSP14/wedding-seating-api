"""
main.py — FastAPI application entry point
------------------------------------------
This file creates the API and defines every HTTP endpoint.

How FastAPI works (simple version):
  1. You create an "app" object.
  2. You decorate Python functions with @app.get("/some/path") or
     @app.post("/some/path").
  3. When someone sends an HTTP request to that path, FastAPI runs your
     function and returns whatever it returns as a JSON response.

FastAPI also auto-generates interactive documentation at:
  http://localhost:8000/docs   ← you can test every endpoint from a browser

Endpoints we expose:
  GET  /                          health check — "is the API alive?"
  POST /api/seating/run           run the algorithm and SAVE results to DB
  GET  /api/seating/preview       run the algorithm but do NOT save (dry run)
  GET  /api/seating/tables        show the current saved assignments
  DELETE /api/seating/reset       clear all saved assignments
"""

import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict

from loader import (
    load_confirmed_guests,
    load_no_separar_de_pairs,
    load_no_sentar_con_pairs,
    load_pinned_assignments,
    load_tables,
)
from classifier import build_clusters
from assigner import assign_tables
from saver import save_assignments, clear_assignments, load_current_assignments
from models import SeatingResult, TableResult, GuestSummary, Cluster

# Load .env before anything else reads os.getenv()
load_dotenv()

MIN_CAP = int(os.getenv("MIN_GUESTS_PER_TABLE", 8))
MAX_CAP = int(os.getenv("MAX_GUESTS_PER_TABLE", 12))

# Force specific clusters to specific tables before the greedy loop runs.
# Key = any guest ID that belongs to the cluster you want to pin.
# Value = the table_id that cluster must occupy.
#   Guest 1  (Cornelio Sánchez) → table 1 (Central Perk)  — Sánchez Peña family
#   Guest 5  (Roberto Torres Pla) → table 2 (The Yellow Frame) — Torres Johnson family
GUEST_PIN: dict[int, int] = {
    1: 1,
    5: 2,
}

# ── Create the FastAPI app ────────────────────────────────────────────────────
# title and description appear in the auto-generated docs at /docs
app = FastAPI(
    title="Wedding Seating Algorithm",
    description="Classifies confirmed guests into clusters and assigns them to tables.",
    version="1.0.0",
)

# Allow the frontend (any origin during development) to call this API.
# In production you can restrict allow_origins to your actual frontend URL.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Helper: run the full algorithm pipeline ───────────────────────────────────
def _run_pipeline() -> tuple[dict, list[str], dict, dict, list]:
    """
    Shared logic used by both /run and /preview.
    Returns everything the endpoints need:
      - assignments       : {guest_id: table_id}
      - warnings          : list of warning strings
      - guests_by_id      : {guest_id: Guest}
      - clusters_by_guest : {guest_id: Cluster}
      - tables            : list of Table objects
    """
    # ── Step 1: Load data from DB ─────────────────────────────────────────
    guests        = load_confirmed_guests()
    separar_pairs = load_no_separar_de_pairs()
    sentar_pairs  = load_no_sentar_con_pairs()
    tables        = load_tables()

    if not guests:
        raise HTTPException(status_code=404, detail="No confirmed guests found.")
    if not tables:
        raise HTTPException(status_code=404, detail="No tables found in tables_event.")

    # ── Step 2: Validate that guests fit ──────────────────────────────────
    max_total = sum(min(t.capacity, MAX_CAP) for t in tables)
    if len(guests) > max_total:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(guests)} confirmed guests cannot fit in {len(tables)} tables "
                f"with a combined max capacity of {max_total}."
            ),
        )

    # ── Step 3: Build index dicts ─────────────────────────────────────────
    guests_by_id = {g.id: g for g in guests}

    # ── Step 4: Classify — build clusters ────────────────────────────────
    clusters = build_clusters(guests, separar_pairs)

    # Build a reverse lookup: guest_id → which cluster it belongs to.
    # This is used by the saver to write the "reason" field.
    clusters_by_guest: dict[int, Cluster] = {}
    for cluster in clusters:
        for gid in cluster.guest_ids:
            clusters_by_guest[gid] = cluster

    # ── Step 5: Merge hardcoded pins with admin-pinned DB assignments ─────
    # Admin moves (pinned=1 in table_assignments) take precedence and are
    # merged on top of the hardcoded GUEST_PIN dict.
    db_pins = load_pinned_assignments()
    # Only pin guests that are actually confirmed (in guests_by_id).
    effective_pin = {
        gid: tid
        for gid, tid in {**GUEST_PIN, **db_pins}.items()
        if gid in guests_by_id
    }

    # ── Step 6: Assign clusters to tables ────────────────────────────────
    assignments, warnings = assign_tables(
        clusters=clusters,
        guests_by_id=guests_by_id,
        no_sentar_con_pairs=sentar_pairs,
        tables=tables,
        min_capacity=MIN_CAP,
        max_capacity=MAX_CAP,
        guest_pin=effective_pin,
    )

    return assignments, warnings, guests_by_id, clusters_by_guest, tables


def _build_result(assignments, warnings, guests_by_id, tables) -> SeatingResult:
    """
    Convert raw {guest_id: table_id} assignments into a structured
    SeatingResult that FastAPI will serialize to JSON.
    """
    # Group assignments by table: {table_id: [guest_id, guest_id, ...]}
    table_to_guests: dict[int, list[int]] = defaultdict(list)
    for guest_id, table_id in assignments.items():
        table_to_guests[table_id].append(guest_id)

    tables_by_id = {t.id: t for t in tables}

    table_results: list[TableResult] = []
    for table_id, guest_ids in sorted(table_to_guests.items()):
        guest_summaries = [
            GuestSummary(
                id=guests_by_id[gid].id,
                name=guests_by_id[gid].name,
                last_name=guests_by_id[gid].last_name,
                parentesco=guests_by_id[gid].parentesco,
                genero=guests_by_id[gid].genero,
                movilidad_reducida=guests_by_id[gid].movilidad_reducida,
            )
            for gid in sorted(guest_ids)
        ]
        table_results.append(
            TableResult(
                table_id=table_id,
                table_name=tables_by_id[table_id].name,
                guest_count=len(guest_ids),
                guests=guest_summaries,
            )
        )

    return SeatingResult(
        total_guests_assigned=len(assignments),
        tables=table_results,
        warnings=warnings,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def health_check():
    """
    Simple health check.
    If this returns 200, the API is running and can reach the database.
    """
    return {"status": "ok", "message": "Seating API is running."}


@app.post("/api/seating/run", response_model=SeatingResult, tags=["Seating"])
def run_seating():
    """
    Run the full algorithm and SAVE the results to table_assignments.

    Use this when you're happy with the setup and want to commit the plan.
    Running it again will OVERWRITE the previous assignment (upsert).
    """
    assignments, warnings, guests_by_id, clusters_by_guest, tables = _run_pipeline()

    # Persist results to DB
    save_assignments(assignments, guests_by_id, clusters_by_guest)

    return _build_result(assignments, warnings, guests_by_id, tables)


@app.get("/api/seating/preview", response_model=SeatingResult, tags=["Seating"])
def preview_seating():
    """
    Run the algorithm but do NOT save anything to the database.

    Use this to see what the algorithm would produce before committing.
    Nothing in the DB changes.
    """
    assignments, warnings, guests_by_id, _clusters_by_guest, tables = _run_pipeline()
    return _build_result(assignments, warnings, guests_by_id, tables)


@app.get("/api/seating/tables", tags=["Seating"])
def get_current_tables():
    """
    Return the currently saved table assignments from the DB,
    grouped by table name.
    """
    rows = load_current_assignments()
    if not rows:
        return {"message": "No assignments saved yet. Run /api/seating/run first."}

    # Group rows by table_name using defaultdict.
    # defaultdict(list) means: if the key doesn't exist yet, create an empty list.
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["table_name"]].append({
            "guest_id":          row["guest_id"],
            "name":              row["name"],
            "last_name":         row["last_name"],
            "parentesco":        row["parentesco"],
            "genero":            row["genero"],
            "movilidad_reducida": row["movilidad_reducida"],
            "reason":            row["reason"],
        })

    return {
        "total_assigned": len(rows),
        "tables": [
            {"table_name": name, "guest_count": len(guests), "guests": guests}
            for name, guests in sorted(grouped.items())
        ],
    }


@app.delete("/api/seating/reset", tags=["Seating"])
def reset_seating():
    """
    Delete all rows from table_assignments.
    Use this to start fresh before running the algorithm again.
    """
    clear_assignments()
    return {"status": "ok", "message": "All table assignments have been cleared."}

"""
assigner.py — Phase 2: Assign clusters to tables
--------------------------------------------------
Now that we have clusters (indivisible groups), we need to place each one
at a table. This is a GREEDY algorithm.

What does "greedy" mean?
  At each step, we pick the BEST available option RIGHT NOW without looking
  ahead. It's like packing suitcases: you put the biggest items in first,
  then fill the gaps with smaller ones.

Our strategy:
  1. Sort clusters largest → smallest ("First Fit Decreasing").
     Large clusters are hardest to place — handle them first while tables
     are still empty and have room.

  2. For each cluster, find every table where it can legally go:
       - Table has enough remaining seats  (hard constraint)
       - No no_sentar_con conflict exists  (hard constraint)
       - If the table is at or above FILL_THRESHOLD seats, only allow
         placement if the cluster shares a parentesco or family with the
         existing occupants (soft-hard constraint with fallback).

  3. Among legal tables, pick the one with the HIGHEST SCORE:
       +10 per existing guest with the same parentesco   (soft)
       +5  per existing guest with the same family_id    (soft)
       +1  per existing guest (encourages filling tables evenly) (soft)

  4. If no legal table exists for a cluster → add a warning, skip it.
     (This shouldn't happen with correct data, but we handle it gracefully.)
"""

from models import Guest, Cluster, Table

# If a table already has this many guests, we only place a new cluster there
# if it shares at least one parentesco or family with the current occupants.
# This avoids forcing unrelated guests into the last seat(s) of a table.
# If NO table passes this stricter check, we fall back to normal placement
# so no guest is ever left unassigned due to this rule alone.
FILL_THRESHOLD = 11


def assign_tables(
    clusters: list[Cluster],
    guests_by_id: dict[int, Guest],
    no_sentar_con_pairs: list[tuple[int, int]],
    tables: list[Table],
    min_capacity: int = 8,
    max_capacity: int = 12,
    guest_pin: dict[int, int] | None = None,
) -> tuple[dict[int, int], list[str]]:
    """
    Run the greedy assignment and return:
      - assignments : dict mapping guest_id → table_id
      - warnings    : list of human-readable problem descriptions

    Parameters:
      clusters            — output of classifier.build_clusters()
      guests_by_id        — {guest_id: Guest} lookup dict
      no_sentar_con_pairs — pairs of guests that CANNOT share a table
      tables              — list of Table objects from the DB
      min_capacity        — minimum guests a table should have (used for warnings)
      max_capacity        — hard ceiling per table
      guest_pin           — optional {guest_id: table_id} — forces the cluster
                            that contains that guest to the specified table before
                            the greedy loop runs (used to reserve tables 1 and 2
                            for the main families).
    """

    # ── Build a fast conflict lookup ─────────────────────────────────────────
    conflict_set: set[tuple[int, int]] = set()
    for a, b in no_sentar_con_pairs:
        conflict_set.add((a, b))
        conflict_set.add((b, a))

    # ── Identify accessible tables ───────────────────────────────────────────
    accessible_table_ids: set[int] = {
        t.id for t in tables
        if t.notes and "accesible" in t.notes.lower()
    }

    # ── State tracking ───────────────────────────────────────────────────────
    table_occupants: dict[int, list[int]] = {t.id: [] for t in tables}
    table_cap: dict[int, int] = {t.id: min(t.capacity, max_capacity) for t in tables}

    assignments: dict[int, int] = {}
    warnings: list[str] = []

    # ── Sort clusters: largest first ─────────────────────────────────────────
    sorted_clusters = sorted(clusters, key=lambda c: c.size, reverse=True)

    # ── Pre-assign pinned clusters BEFORE the greedy loop ────────────────────
    # If guest_pin = {1: 1, 5: 2}, the cluster containing guest 1 is forced to
    # table 1, and the cluster containing guest 5 is forced to table 2.
    # This ensures priority families always land on their designated tables.
    remaining_clusters: list[Cluster] = []
    if guest_pin:
        pinned_table_ids: set[int] = set()
        for cluster in sorted_clusters:
            pinned_to: int | None = None
            for gid in cluster.guest_ids:
                if gid in guest_pin:
                    pinned_to = guest_pin[gid]
                    break

            if pinned_to is not None and pinned_to not in pinned_table_ids:
                target_cap = table_cap[pinned_to]
                if cluster.size <= target_cap:
                    for gid in cluster.guest_ids:
                        table_occupants[pinned_to].append(gid)
                        assignments[gid] = pinned_to
                    pinned_table_ids.add(pinned_to)
                else:
                    warnings.append(
                        f"Pinned cluster {cluster.guest_ids} (size {cluster.size}) "
                        f"exceeds capacity of table {pinned_to}. Falling through to greedy."
                    )
                    remaining_clusters.append(cluster)
            else:
                remaining_clusters.append(cluster)
        sorted_clusters = remaining_clusters

    # ── Main loop: place one cluster at a time ───────────────────────────────
    for cluster in sorted_clusters:

        # Safety check: if a single cluster is bigger than any table can hold,
        # we can never place it. Warn and skip — this is a data problem.
        if cluster.size > max_capacity:
            warnings.append(
                f"Cluster with guests {cluster.guest_ids} has {cluster.size} members "
                f"which exceeds max_capacity={max_capacity}. Skipped."
            )
            continue

        # ── Find every table where this cluster can legally go ───────────────
        # Try with the threshold rule first (prefer tables with matching group).
        # Fall back to unrestricted placement so no guest is ever left out.
        legal_tables = _find_legal_tables(
            cluster, tables, table_cap, table_occupants, conflict_set,
            guests_by_id, apply_threshold=True
        )
        if not legal_tables:
            legal_tables = _find_legal_tables(
                cluster, tables, table_cap, table_occupants, conflict_set,
                guests_by_id, apply_threshold=False
            )

        if not legal_tables:
            warnings.append(
                f"No valid table found for cluster {cluster.guest_ids}. "
                f"Check no_sentar_con constraints or table capacities."
            )
            continue

        # ── Among legal tables, pick the best-scoring one ────────────────────
        best_table = max(
            legal_tables,
            key=lambda t: _score_table(
                cluster, t, table_occupants[t.id], guests_by_id, accessible_table_ids
            ),
        )

        # ── Assign all guests in the cluster to the chosen table ─────────────
        for guest_id in cluster.guest_ids:
            table_occupants[best_table.id].append(guest_id)
            assignments[guest_id] = best_table.id

    # ── Post-assignment: warn about tables that are under the minimum ─────────
    for table in tables:
        count = len(table_occupants[table.id])
        if 0 < count < min_capacity:
            warnings.append(
                f"Table '{table.name}' has only {count} guests (minimum is {min_capacity})."
            )

    return assignments, warnings


def _find_legal_tables(
    cluster: Cluster,
    tables: list[Table],
    table_cap: dict[int, int],
    table_occupants: dict[int, list[int]],
    conflict_set: set[tuple[int, int]],
    guests_by_id: dict[int, Guest],
    apply_threshold: bool,
) -> list[Table]:
    """
    Return all tables where this cluster can legally be placed.

    When apply_threshold=True, tables at or above FILL_THRESHOLD are skipped
    unless the cluster shares a parentesco or family with existing occupants.
    """
    result: list[Table] = []
    cluster_parentescos = set(cluster.parentesco_votes.keys())

    for table in tables:
        occupants = table_occupants[table.id]
        remaining_seats = table_cap[table.id] - len(occupants)

        if remaining_seats < cluster.size:
            continue

        if _has_conflict(cluster.guest_ids, occupants, conflict_set):
            continue

        if apply_threshold and len(occupants) >= FILL_THRESHOLD:
            table_parentescos = {guests_by_id[g].parentesco for g in occupants}
            table_families    = {guests_by_id[g].family_id  for g in occupants}
            if not (cluster_parentescos & table_parentescos) and \
               not (cluster.family_ids  & table_families):
                continue

        result.append(table)

    return result


def _has_conflict(
    cluster_ids: list[int],
    table_guest_ids: list[int],
    conflict_set: set[tuple[int, int]],
) -> bool:
    """
    Return True if placing this cluster at the table would put any
    no_sentar_con pair at the same table.

    We check every combination of (cluster guest, table guest).
    As soon as we find ONE conflict we stop and return True immediately —
    no need to check the rest.
    """
    for c in cluster_ids:
        for t in table_guest_ids:
            if (c, t) in conflict_set:
                return True
    return False


# Parentesco incompatibility table.
# Format: (group_A, group_B, penalty_per_conflicting_guest)
# The penalty applies in BOTH directions (A→B and B→A).
# Higher penalty = stronger separation.
INCOMPATIBLE_PARENTESCO: list[tuple[str, str, int]] = [
    # Families away from all church groups (strong: 30 pts per guest)
    ("FAM_AXEL", "IGLESIA_VAL",     30),
    ("FAM_AXEL", "IGLESIA_AXEL",    30),
    ("FAM_AXEL", "IGLESIA_EXTERNA", 30),
    ("FAM_VAL",  "IGLESIA_VAL",     30),
    ("FAM_VAL",  "IGLESIA_AXEL",    30),
    ("FAM_VAL",  "IGLESIA_EXTERNA", 30),
]


def _score_table(
    cluster: Cluster,
    table: Table,
    current_occupants: list[int],
    guests_by_id: dict[int, Guest],
    accessible_table_ids: set[int],
) -> int:
    """
    Calculate how "good" it would be to put this cluster at this table.
    Higher score = better fit.

    Scoring breakdown:
      +10  per existing guest at this table with the same parentesco
      +5   per existing guest at this table with the same family_id
      +1   per existing guest (encourages filling tables before opening new ones)
      +50  if the cluster has mobility needs AND this is an accessible table
      -30  per existing guest whose parentesco is incompatible with the cluster
           (soft discouragement — not a hard block like no_sentar_con)
    """
    score = 0

    # Pre-collect the parentesco and family of everyone already at the table.
    table_parentescos = [guests_by_id[g].parentesco for g in current_occupants]
    table_families    = [guests_by_id[g].family_id  for g in current_occupants]

    # Parentesco bonus.
    for parentesco in cluster.parentesco_votes:
        score += table_parentescos.count(parentesco) * 10

    # Family bonus.
    for family_id in cluster.family_ids:
        score += table_families.count(family_id) * 5

    # Fill-evenly bonus.
    score += len(current_occupants)

    # Accessibility bonus.
    if cluster.has_mobility and table.id in accessible_table_ids:
        score += 50

    # Incompatibility penalty: check both directions of each pair.
    for a, b, penalty in INCOMPATIBLE_PARENTESCO:
        if a in cluster.parentesco_votes:
            score -= table_parentescos.count(b) * penalty
        if b in cluster.parentesco_votes:
            score -= table_parentescos.count(a) * penalty

    return score

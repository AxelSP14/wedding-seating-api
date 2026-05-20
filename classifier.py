"""
classifier.py — Phase 1: Build clusters from guests
------------------------------------------------------
A CLUSTER is a group of guests that must sit at the same table.
We build clusters using a GRAPH.

What is a graph?
  A graph is just a collection of dots (nodes) connected by lines (edges).
  Here:
    - Each guest is a dot.
    - A line between two guests means "these two must sit together".

  Once we draw all the lines, we look for islands — groups of dots that
  are connected to each other but not to anyone outside the group.
  Each island becomes one cluster.

  Example:
    A — B — C        D — E
    Island 1: {A, B, C}   →  one cluster, must share a table
    Island 2: {D, E}       →  another cluster

We use the NetworkX library because it can find these islands for us
in one line of code (connected_components).

Priority order for adding edges:
  1. depende_de_guest_id  — guest A explicitly depends on guest B
  2. no_separar_de pairs  — these two must never be split up
  3. same family_id       — guests in the same family stay together
"""

import networkx as nx
from models import Guest, Cluster


def build_clusters(
    guests: list[Guest],
    no_separar_de_pairs: list[tuple[int, int]],
) -> list[Cluster]:
    """
    Main function: takes guests + must-sit-together rules,
    returns a list of Cluster objects.

    Steps:
      1. Create a graph node for every confirmed guest.
      2. Add edges for depende_de_guest_id relationships.
      3. Add edges for no_separar_de pairs.
      4. Add edges for guests in the same family (keeps families together).
      5. Find connected components → each component = one cluster.
      6. Annotate each cluster with metadata (parentesco, family, mobility).
    """

    # Build a quick lookup: guest_id → Guest object.
    guests_by_id: dict[int, Guest] = {g.id: g for g in guests}

    # Collect only the IDs of confirmed guests so we can filter out
    # any no_separar_de references that point to non-confirmed guests.
    confirmed_ids: set[int] = set(guests_by_id.keys())

    # ── Step 1: Create an empty undirected graph ─────────────────────────────
    graph = nx.Graph()
    graph.add_nodes_from(confirmed_ids)

    # ── Step 2: Add edges for depende_de_guest_id ────────────────────────────
    for guest in guests:
        dep = guest.depende_de_guest_id
        if dep is not None and dep in confirmed_ids:
            graph.add_edge(guest.id, dep)

    # ── Step 3: Add edges for no_separar_de pairs ────────────────────────────
    for a, b in no_separar_de_pairs:
        if a in confirmed_ids and b in confirmed_ids:
            graph.add_edge(a, b)

    # ── Step 4: Add edges for same family_id (don't separate families) ───────
    # Build a map of family_id → [guest_ids] for confirmed guests only.
    family_groups: dict[int, list[int]] = {}
    for guest in guests:
        family_groups.setdefault(guest.family_id, []).append(guest.id)

    # Connect each family into a chain: A-B-C-D → A—B, B—C, C—D.
    # A chain is enough for NetworkX to treat them as one connected component.
    for members in family_groups.values():
        confirmed_members = [m for m in members if m in confirmed_ids]
        for i in range(len(confirmed_members) - 1):
            graph.add_edge(confirmed_members[i], confirmed_members[i + 1])

    # ── Step 5: Find connected components ────────────────────────────────────
    components = list(nx.connected_components(graph))

    # ── Step 6: Build Cluster objects from each component ────────────────────
    clusters: list[Cluster] = []
    for component in components:
        cluster = _build_cluster(component, guests_by_id)
        clusters.append(cluster)

    return clusters


def _build_cluster(guest_ids: set[int], guests_by_id: dict[int, Guest]) -> Cluster:
    """
    Given a set of guest IDs (one connected component),
    build and return a Cluster object with all its metadata.
    """
    cluster = Cluster(guest_ids=list(guest_ids))

    for gid in guest_ids:
        guest = guests_by_id[gid]

        # Count parentesco votes.
        # setdefault(key, 0) means: if key doesn't exist yet, start it at 0.
        cluster.parentesco_votes.setdefault(guest.parentesco, 0)
        cluster.parentesco_votes[guest.parentesco] += 1

        # Collect all family IDs in this cluster.
        cluster.family_ids.add(guest.family_id)

        # If ANY guest in the cluster needs accessible seating,
        # the whole cluster is flagged — they all sit at the accessible table.
        if guest.movilidad_reducida:
            cluster.has_mobility = True

    return cluster

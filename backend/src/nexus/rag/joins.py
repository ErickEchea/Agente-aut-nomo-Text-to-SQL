"""Join paths over the foreign-key graph: connect the selected tables, adding bridge tables.

A greedy Steiner-tree approximation: start from the highest-ranked table and repeatedly attach the
closest remaining terminal through its shortest FK path. Optimal for the small schemas we target and
always yields a connected set.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from nexus.agent.catalog import SchemaCatalog


@dataclass(frozen=True, slots=True)
class JoinEdge:
    left_table: str
    left_column: str
    right_table: str
    right_column: str

    def condition(self) -> str:
        return f"{self.left_table}.{self.left_column} = {self.right_table}.{self.right_column}"


def _graph(catalog: SchemaCatalog) -> dict[str, list[tuple[str, JoinEdge]]]:
    graph: dict[str, list[tuple[str, JoinEdge]]] = {name: [] for name in catalog.tables}
    for table in catalog.tables.values():
        for fk in table.foreign_keys:
            if fk.ref_table == table.name or fk.ref_table not in graph:
                continue  # self references (supervisor_id) do not connect tables
            edge = JoinEdge(table.name, fk.column, fk.ref_table, fk.ref_column)
            graph[table.name].append((fk.ref_table, edge))
            graph[fk.ref_table].append((table.name, edge))
    return graph


def _shortest_path(
    graph: dict[str, list[tuple[str, JoinEdge]]], sources: set[str], target: str
) -> list[JoinEdge] | None:
    """BFS from any table already in the tree to ``target``; returns the edges on the path."""
    previous: dict[str, tuple[str, JoinEdge] | None] = dict.fromkeys(sources)
    queue = deque(sorted(sources))
    while queue:
        node = queue.popleft()
        if node == target:
            path: list[JoinEdge] = []
            while previous[node] is not None:
                parent, edge = previous[node]  # type: ignore[misc]
                path.append(edge)
                node = parent
            return path[::-1]
        for neighbour, edge in sorted(graph.get(node, []), key=lambda item: item[0]):
            if neighbour not in previous:
                previous[neighbour] = (node, edge)
                queue.append(neighbour)
    return None


def connect(catalog: SchemaCatalog, terminals: Sequence[str]) -> tuple[list[str], list[JoinEdge]]:
    """(tables in the connecting tree, join edges); unreachable terminals are kept, unjoined."""
    wanted = [t for t in dict.fromkeys(terminals) if t in catalog.tables]
    if not wanted:
        return [], []
    graph = _graph(catalog)
    tree = {wanted[0]}
    edges: list[JoinEdge] = []
    remaining = wanted[1:]
    while remaining:
        best: tuple[str, list[JoinEdge]] | None = None
        for terminal in remaining:
            path = _shortest_path(graph, tree, terminal)
            if path is not None and (best is None or len(path) < len(best[1])):
                best = (terminal, path)
        if best is None:  # disconnected component: include without a join hint
            tree.update(remaining)
            break
        terminal, path = best
        for edge in path:
            if edge not in edges:
                edges.append(edge)
            tree.update((edge.left_table, edge.right_table))
        remaining = [t for t in remaining if t not in tree]
    ordered = [t for t in wanted if t in tree] + sorted(tree - set(wanted))
    return ordered, edges

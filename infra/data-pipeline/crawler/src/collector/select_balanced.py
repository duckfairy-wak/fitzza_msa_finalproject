from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from src.collector.config import CATEGORY_CONFIG
from src.collector.rules import has_required_size
from src.collector.season_allocator import possible_seasons


SEASONS = ["봄", "여름", "가을", "겨울"]


class Edge:
    def __init__(self, to: int, rev: int, cap: int) -> None:
        self.to = to
        self.rev = rev
        self.cap = cap


class Dinic:
    def __init__(self, n: int) -> None:
        self.graph: list[list[Edge]] = [[] for _ in range(n)]

    def add_edge(self, fr: int, to: int, cap: int) -> None:
        fwd = Edge(to, len(self.graph[to]), cap)
        rev = Edge(fr, len(self.graph[fr]), 0)
        self.graph[fr].append(fwd)
        self.graph[to].append(rev)

    def max_flow(self, source: int, sink: int) -> int:
        flow = 0
        n = len(self.graph)

        while True:
            level = [-1] * n
            level[source] = 0
            q = deque([source])

            while q:
                v = q.popleft()
                for e in self.graph[v]:
                    if e.cap > 0 and level[e.to] < 0:
                        level[e.to] = level[v] + 1
                        q.append(e.to)

            if level[sink] < 0:
                return flow

            it = [0] * n

            def dfs(v: int, f: int) -> int:
                if v == sink:
                    return f

                while it[v] < len(self.graph[v]):
                    e = self.graph[v][it[v]]

                    if e.cap > 0 and level[v] < level[e.to]:
                        d = dfs(e.to, min(f, e.cap))
                        if d > 0:
                            e.cap -= d
                            self.graph[e.to][e.rev].cap += d
                            return d

                    it[v] += 1

                return 0

            while True:
                f = dfs(source, 10**9)
                if f == 0:
                    break
                flow += f


def load_products(category: str) -> list[dict[str, Any]]:
    root = Path("data/screened") / category
    products: list[dict[str, Any]] = []
    season_balance_required = CATEGORY_CONFIG[category].get(
        "season_balance_required",
        True,
    )

    if not root.exists():
        return products

    for path in sorted(root.glob("*.json")):
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        if not has_required_size(product, category):
            continue

        candidates, source = possible_seasons(product)
        if not candidates and season_balance_required:
            continue

        product["_selection_candidates"] = candidates
        product["_selection_source"] = source
        products.append(product)

    # 후보 계절이 적은 상품부터 product node를 배치하면
    # restrictive item이 먼저 경로를 잡아 결과가 더 안정적이다.
    if season_balance_required:
        products.sort(
            key=lambda p: (
                len(p["_selection_candidates"]),
                int(p["product_id"]),
            )
        )
    else:
        products.sort(
            key=lambda p: (
                not bool(p["_selection_candidates"]),
                int(p["product_id"]),
            )
        )
    return products


def select_without_season_quota(
    category: str,
    products: list[dict[str, Any]],
) -> dict[str, Any]:
    config = CATEGORY_CONFIG[category]
    required = config["total_quota"]
    counts = {season: 0 for season in SEASONS}
    selected: list[dict[str, Any]] = []

    for product in products[:required]:
        candidates = product["_selection_candidates"]
        assigned = (
            min(candidates, key=lambda season: (counts[season], SEASONS.index(season)))
            if candidates
            else None
        )
        if assigned:
            counts[assigned] += 1

        selected.append(
            {
                "product_id": product["product_id"],
                "primary_season": assigned,
                "primary_source": (
                    product["_selection_source"] if assigned else "not_available"
                ),
                "primary_candidates": candidates,
                "gender": product.get("gender", {}).get("normalized"),
                "collection": product.get("season", {}).get("collection"),
            }
        )

    return {
        "category": category,
        "required": required,
        "screened_usable": len(products),
        "selected": len(selected),
        "complete": len(selected) == required,
        "season_balance_required": False,
        "quota": config["season_quota"],
        "counts": counts,
        "deficit": None,
        "items": selected,
    }


def select_category(category: str) -> dict[str, Any]:
    products = load_products(category)
    config = CATEGORY_CONFIG[category]
    if not config.get("season_balance_required", True):
        return select_without_season_quota(category, products)

    quotas = config["season_quota"]
    required = config["total_quota"]

    product_count = len(products)

    source = 0
    product_start = 1
    season_start = product_start + product_count
    sink = season_start + len(SEASONS)
    graph = Dinic(sink + 1)

    season_node = {
        season: season_start + i
        for i, season in enumerate(SEASONS)
    }

    for i, product in enumerate(products):
        pnode = product_start + i
        graph.add_edge(source, pnode, 1)

        for season in product["_selection_candidates"]:
            graph.add_edge(pnode, season_node[season], 1)

    for season in SEASONS:
        graph.add_edge(season_node[season], sink, quotas[season])

    flow = graph.max_flow(source, sink)

    selected: list[dict[str, Any]] = []
    counts = {season: 0 for season in SEASONS}

    for i, product in enumerate(products):
        pnode = product_start + i
        assigned = None

        for edge in graph.graph[pnode]:
            for season, snode in season_node.items():
                if edge.to == snode and edge.cap == 0:
                    assigned = season
                    break
            if assigned:
                break

        if not assigned:
            continue

        counts[assigned] += 1

        selected.append(
            {
                "product_id": product["product_id"],
                "primary_season": assigned,
                "primary_source": product["_selection_source"],
                "primary_candidates": product["_selection_candidates"],
                "gender": product.get("gender", {}).get("normalized"),
                "collection": product.get("season", {}).get("collection"),
            }
        )

    return {
        "category": category,
        "required": required,
        "screened_usable": len(products),
        "selected": len(selected),
        "complete": flow == required,
        "season_balance_required": True,
        "quota": quotas,
        "counts": counts,
        "deficit": {
            season: max(0, quotas[season] - counts[season])
            for season in SEASONS
        },
        "items": selected,
    }


def main() -> None:
    output_dir = Path("data/selection")
    output_dir.mkdir(parents=True, exist_ok=True)

    overall = {}

    for category in CATEGORY_CONFIG:
        result = select_category(category)
        overall[category] = {
            key: value
            for key, value in result.items()
            if key != "items"
        }

        path = output_dir / f"{category}.json"
        path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(
            f"{category:4}: "
            f"selected {result['selected']}/{result['required']} "
            f"| {result['counts']} "
            f"| complete={result['complete']}"
        )

    summary_path = output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(overall, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nsummary: {summary_path}")


if __name__ == "__main__":
    main()

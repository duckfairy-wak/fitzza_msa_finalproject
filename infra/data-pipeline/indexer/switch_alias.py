"""Atomically point a Qdrant alias at a validated collection, or show the current target.

Run manually (port-forward or a Pod labeled fitzza.io/qdrant-client=true) only after
import_job reported passed=true and the import report has been reviewed.
The previous target is printed so the same command can roll back. No collection is deleted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def alias_target(client, alias: str) -> str | None:
    for item in client.get_aliases().aliases:
        if item.alias_name == alias:
            return item.collection_name
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qdrant-url", default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
    parser.add_argument("--alias", required=True)
    parser.add_argument("--collection", help="collection to point the alias at; omit to only show the target")
    parser.add_argument("--expected-points", type=int, help="refuse to switch unless the collection has exactly this many points")
    parser.add_argument("--apply", action="store_true", help="perform the switch; without it, print the plan only")
    args = parser.parse_args()
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=args.qdrant_url, timeout=30)
    current = alias_target(client, args.alias)
    # collection_exists() also resolves aliases, so compare against physical collection names.
    physical = {item.name for item in client.get_collections().collections}
    if args.alias in physical:
        sys.exit(f"{args.alias} is a physical collection, not an alias; choose another alias name")
    state = {"alias": args.alias, "old_alias_target": current}
    if not args.collection:
        print(json.dumps(state, ensure_ascii=False))
        return
    if args.collection not in physical:
        sys.exit(f"Collection {args.collection} is not a physical collection")
    count = client.count(collection_name=args.collection, exact=True).count
    state.update(new_alias_target=args.collection, new_collection_point_count=count)
    if args.expected_points is not None and count != args.expected_points:
        sys.exit(f"Point count {count} != expected {args.expected_points}; not switching")
    if not args.apply:
        print(json.dumps({**state, "applied": False}, ensure_ascii=False))
        return
    operations = []
    if current:
        operations.append(models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=args.alias)))
    operations.append(models.CreateAliasOperation(create_alias=models.CreateAlias(
        collection_name=args.collection, alias_name=args.alias)))
    client.update_collection_aliases(change_aliases_operations=operations)
    state.update(applied=True, verified_target=alias_target(client, args.alias))
    print(json.dumps(state, ensure_ascii=False))
    if state["verified_target"] != args.collection:
        sys.exit(1)


if __name__ == "__main__":
    main()

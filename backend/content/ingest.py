"""
Ingest practice items from a seed JSON file into the Postgres `items` bank.

Each item is validated by its per-type validator before insert, so a malformed
item fails loudly at ingest time rather than reaching a user.
"""

import glob
import json
import os

from content.models import Item, validate
from memory.longterm import insert_item
from observability.logger import log

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


def ingest_items(path: str = None) -> dict:
    """Ingest items. With no `path`, ingests every *.json file in content/data/
    (so TC/SE/RC seeds each live in their own file)."""
    paths = [path] if path else sorted(glob.glob(os.path.join(DATA_DIR, "*.json")))

    inserted, errors = 0, []
    for p in paths:
        with open(p) as f:
            raw = json.load(f)
        for entry in raw:
            try:
                item = Item(**entry)
                validate(item)
                insert_item(item.model_dump())
                inserted += 1
            except Exception as exc:  # noqa: BLE001 — report, don't abort the batch
                errors.append({"id": entry.get("id"), "file": os.path.basename(p), "error": str(exc)})
                log("item_ingest_error", item_id=entry.get("id"), error=str(exc))

    log("items_ingested", inserted=inserted, errors=len(errors), files=len(paths))
    return {"inserted": inserted, "errors": errors}

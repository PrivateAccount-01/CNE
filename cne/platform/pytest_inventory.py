"""Small pytest plugin that records the exact collected test IDs for evidence."""
import json
import os
from pathlib import Path


def pytest_collection_finish(session):
    target = os.environ.get("CNE_TEST_INVENTORY_PATH")
    if not target:
        return
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sorted(item.nodeid for item in session.items), indent=2) + "\n",
        encoding="utf-8",
    )

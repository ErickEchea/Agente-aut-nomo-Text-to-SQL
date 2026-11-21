"""Export the HTTP contract (OpenAPI 3.1) without settings, databases or models.

The frontend generates its API types from this file (``make api-types``); a unit test fails when the
committed snapshot drifts from the routes.

Usage: ``python -m nexus.openapi <output.json>``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from nexus import __version__
from nexus.main import ROUTERS

APP_TITLE = "NEXUS AI"


def openapi_schema() -> dict[str, Any]:
    app = FastAPI(title=APP_TITLE, version=__version__, openapi_url="/api/openapi.json")
    for router in ROUTERS:
        app.include_router(router)
    return app.openapi()


def render() -> str:
    # The version is left out of the snapshot so a release bump does not count as contract drift.
    schema = openapi_schema()
    schema["info"].pop("version", None)
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.stderr.write("usage: python -m nexus.openapi <output.json>\n")
        return 2
    Path(argv[0]).write_text(render(), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

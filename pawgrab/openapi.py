"""Dump the FastAPI OpenAPI schema — the single source of truth for every SDK (F5).

    python -m pawgrab.openapi > sdk/openapi.json

All SDKs (python, typescript, go, rust, java, ruby, php, dotnet, elixir) are
generated from this file, so new endpoints (agent, interact, index, ranked map)
appear in every client automatically.
"""

from __future__ import annotations

import sys

import orjson


def generate() -> dict:
    """Return the app's OpenAPI schema as a dict."""
    from pawgrab.main import app

    return app.openapi()


def main() -> None:
    out = orjson.dumps(generate(), option=orjson.OPT_INDENT_2)
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()

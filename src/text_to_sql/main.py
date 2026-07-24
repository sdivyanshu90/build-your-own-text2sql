"""Application entry point.

``app`` is the ASGI application uvicorn/gunicorn import (``text_to_sql.main:app``).
``run()`` is the console-script entry (``text-to-sql``) for local development.
"""

from __future__ import annotations

import uvicorn

from text_to_sql.api.app import create_app
from text_to_sql.configuration import get_settings

# Module-level ASGI app for `uvicorn text_to_sql.main:app`.
app = create_app()


def run() -> None:
    """Run the development server using configured host/port."""
    settings = get_settings()
    uvicorn.run(
        "text_to_sql.main:app",
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,  # we configure structured logging ourselves
    )


if __name__ == "__main__":
    run()

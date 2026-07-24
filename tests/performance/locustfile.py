"""Locust load-test definition.

Run against a running instance (uses the fake provider, so no cost):

    make run                      # in one terminal
    locust -f tests/performance/locustfile.py --host http://localhost:8000

Then open http://localhost:8089. See ``docs/testing/performance.md`` for how to
interpret p50/p95 latency and error rate, and what thresholds to expect.
"""

from __future__ import annotations

import random

try:  # locust is an optional extra; keep import soft so pytest collection never fails.
    from locust import HttpUser, between, task
except ImportError:  # pragma: no cover - only when the 'load' extra isn't installed
    HttpUser = object  # type: ignore[assignment,misc]

    def task(fn):  # type: ignore[no-redef]
        return fn

    def between(_a, _b):  # type: ignore[no-redef]
        return 0


_QUESTIONS = [
    "Show revenue by region",
    "How many orders were placed last month?",
    "What were our top five products by revenue last quarter?",
    "list all products",
    "Which customers have not placed an order in the past 90 days?",
    "What is our MRR?",
]

_HEADERS = {"X-User-Id": "load", "X-Tenant-Id": "1", "X-Roles": "analyst"}


class QueryUser(HttpUser):  # type: ignore[misc]
    wait_time = between(0.1, 0.5)

    @task(4)
    def query(self) -> None:
        question = random.choice(_QUESTIONS)
        self.client.post("/api/v1/query", json={"question": question}, headers=_HEADERS)

    @task(1)
    def preview(self) -> None:
        self.client.post(
            "/api/v1/query/preview",
            json={"question": random.choice(_QUESTIONS)},
            headers=_HEADERS,
        )

    @task(1)
    def health(self) -> None:
        self.client.get("/api/v1/health/ready")

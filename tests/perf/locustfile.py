"""Load test for the demo app's order API.

Run for real, standalone, against the Dockerized demo stack::

    docker compose -f docker/docker-compose.yml up -d --build
    locust -f tests/perf/locustfile.py --host http://localhost:8000

Or headlessly as an in-CI perf gate, see test_perf_gate.py.
"""

from locust import between, task

from backend_agentic.data.fake import unique_id
from backend_agentic.perf.http_user import BackendAgenticHttpUser


class OrderUser(BackendAgenticHttpUser):
    wait_time = between(0.1, 0.5)

    @task(3)
    def create_order(self) -> None:
        self.client.post("/orders", json={"sku": unique_id("sku"), "qty": 1}, name="POST /orders")

    @task(5)
    def list_orders(self) -> None:
        self.client.get("/orders", name="GET /orders")

"""Drive a Locust load test from a pytest scenario and get back a result
assertpy2 can assert on - a perf gate, not a substitute for real load
testing.

Locust is built on gevent, which wants to monkey-patch the standard library
before anything else in the process imports it. Importing Locust into the
same process as the rest of this framework (httpx, SQLAlchemy,
confluent-kafka) would risk exactly that conflict, so :meth:`PerfAgent.run`
shells out to ``python -m locust --headless`` in a subprocess instead and
parses its ``--csv`` output. That also means a real interactive load test -
the Locust web UI, distributed workers - is unaffected: run it the normal
way, `locust -f locustfile.py`, using
:class:`backend_agentic.perf.http_user.BackendAgenticHttpUser` as the base
for the ``User`` classes so a load test picks up the same host config and
correlation-id convention as the functional tests.

A run where requests fail under load is a normal, expected outcome here: it
still produces a full :class:`PerfResult` with a non-zero failure ratio, for
a test to assert against an SLO. Only a locustfile that could not run at all
(a bad path, a syntax error) raises :class:`~backend_agentic.core.exceptions.PerfRunError`.
"""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend_agentic.config import RestSettings
from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.context import TestContext
from backend_agentic.core.exceptions import PerfRunError

_PERCENTILE_COLUMNS: dict[str, str] = {
    "50%": "p50_ms",
    "66%": "p66_ms",
    "75%": "p75_ms",
    "80%": "p80_ms",
    "90%": "p90_ms",
    "95%": "p95_ms",
    "98%": "p98_ms",
    "99%": "p99_ms",
    "99.9%": "p999_ms",
    "99.99%": "p9999_ms",
    "100%": "p100_ms",
}


@dataclass
class PerfEndpointStats:
    method: str
    name: str
    request_count: int
    failure_count: int
    median_ms: float
    average_ms: float
    min_ms: float
    max_ms: float
    requests_per_sec: float
    failures_per_sec: float
    p50_ms: float
    p66_ms: float
    p75_ms: float
    p80_ms: float
    p90_ms: float
    p95_ms: float
    p98_ms: float
    p99_ms: float
    p999_ms: float
    p9999_ms: float
    p100_ms: float

    @property
    def failure_ratio(self) -> float:
        return self.failure_count / self.request_count if self.request_count else 0.0

    @classmethod
    def _from_csv_row(cls, row: dict[str, str]) -> "PerfEndpointStats":
        kwargs: dict[str, object] = dict(
            method=row["Type"],
            name=row["Name"],
            request_count=int(row["Request Count"]),
            failure_count=int(row["Failure Count"]),
            median_ms=float(row["Median Response Time"]),
            average_ms=float(row["Average Response Time"]),
            min_ms=float(row["Min Response Time"]),
            max_ms=float(row["Max Response Time"]),
            requests_per_sec=float(row["Requests/s"]),
            failures_per_sec=float(row["Failures/s"]),
        )
        for column, attr in _PERCENTILE_COLUMNS.items():
            kwargs[attr] = float(row[column])
        return cls(**kwargs)  # type: ignore[arg-type]


@dataclass
class PerfResult:
    endpoints: list[PerfEndpointStats]
    aggregate: PerfEndpointStats
    failures: list[dict[str, str]]
    returncode: int
    stdout: str

    @property
    def failure_ratio(self) -> float:
        return self.aggregate.failure_ratio

    def endpoint(self, name: str) -> PerfEndpointStats:
        for e in self.endpoints:
            if e.name == name:
                return e
        raise KeyError(f"no endpoint named {name!r}; known: {[e.name for e in self.endpoints]}")

    def summary(self) -> str:
        lines = [
            f"Perf run: {self.aggregate.request_count} requests, "
            f"{self.aggregate.failure_count} failed ({self.failure_ratio:.2%}), "
            f"{self.aggregate.requests_per_sec:.1f} req/s"
        ]
        for e in self.endpoints:
            lines.append(
                f"  {e.method:<6} {e.name:<40} reqs={e.request_count:<6} fail={e.failure_count:<5} "
                f"p50={e.p50_ms:.0f}ms p95={e.p95_ms:.0f}ms p99={e.p99_ms:.0f}ms max={e.max_ms:.0f}ms"
            )
        if self.failures:
            lines.append("  sample failures:")
            for f in self.failures[:10]:
                lines.append(f"    {f}")
        return "\n".join(lines)

    @classmethod
    def _from_csv(cls, csv_prefix: Path, *, returncode: int, stdout: str) -> "PerfResult":
        rows = list(csv.DictReader(Path(f"{csv_prefix}_stats.csv").read_text().splitlines()))
        endpoints = [PerfEndpointStats._from_csv_row(r) for r in rows if r["Name"] != "Aggregated"]
        aggregate = PerfEndpointStats._from_csv_row(next(r for r in rows if r["Name"] == "Aggregated"))

        failures_path = Path(f"{csv_prefix}_failures.csv")
        failures = (
            list(csv.DictReader(failures_path.read_text().splitlines())) if failures_path.exists() else []
        )
        return cls(endpoints=endpoints, aggregate=aggregate, failures=failures, returncode=returncode, stdout=stdout)


class PerfAgent(BaseAgent):
    name = "perf"

    def __init__(self, context: TestContext, rest_settings: RestSettings) -> None:
        super().__init__(context)
        self.rest_settings = rest_settings

    def run(
        self,
        locustfile: str | Path,
        *,
        user_classes: list[str] | None = None,
        users: int = 10,
        spawn_rate: float = 10.0,
        run_time: str = "30s",
        host: str | None = None,
        extra_args: list[str] | None = None,
    ) -> PerfResult:
        """Run ``locustfile`` headlessly for ``run_time`` and return the result.

        ``user_classes`` names which ``User`` classes in the file to run (all
        of them, if omitted). Requires the ``perf`` extra
        (``pip install backend-agentic[perf]``) on ``PATH``/in this
        interpreter - if Locust isn't importable, that surfaces in the
        subprocess's stderr, included in the raised
        :class:`~backend_agentic.core.exceptions.PerfRunError`.
        """
        detail = f"{Path(locustfile).name} users={users} run_time={run_time}"
        with self.step("run", detail=detail):
            with tempfile.TemporaryDirectory(prefix="backend-agentic-perf-") as tmp:
                csv_prefix = Path(tmp) / "run"
                cmd = [
                    sys.executable,
                    "-m",
                    "locust",
                    "-f",
                    str(locustfile),
                    "--headless",
                    "-u",
                    str(users),
                    "-r",
                    str(spawn_rate),
                    "-t",
                    run_time,
                    "--host",
                    host or self.rest_settings.base_url,
                    "--csv",
                    str(csv_prefix),
                    "--loglevel",
                    "WARNING",
                    *(user_classes or []),
                    *(extra_args or []),
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                stats_path = Path(f"{csv_prefix}_stats.csv")
                if not stats_path.exists():
                    raise PerfRunError(
                        f"locust did not produce stats (exit code {proc.returncode}).\n"
                        f"cmd: {' '.join(cmd)}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
                    )
                return PerfResult._from_csv(csv_prefix, returncode=proc.returncode, stdout=proc.stdout)

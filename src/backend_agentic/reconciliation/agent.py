"""Key-based reconciliation between two datasets, powered by polars.

The typical shape of a reconciliation scenario: pull the "source of truth"
from one system (a DB table) and the "downstream" view from another (a REST
listing, a Kafka topic snapshot, a CSV export) as two ``pl.DataFrame``s using
:mod:`backend_agentic.reconciliation.loaders`, then::

    result = recon_agent.compare(left, right, keys=["order_id"], tolerance={"amount": 0.01})
    assert_that(result).is_fully_reconciled()

``compare`` runs a single outer join on ``keys`` and classifies every row into
exactly one of ``matched`` / ``only_in_left`` / ``only_in_right`` / a member of
the long-format ``mismatches`` frame (one row per differing column), rather
than a value-by-value Python loop, so it stays fast on real table sizes.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import polars as pl

from backend_agentic.core.agent import BaseAgent
from backend_agentic.core.exceptions import ReconciliationSourceError


@dataclass
class ReconciliationResult:
    keys: list[str]
    matched: pl.DataFrame
    only_in_left: pl.DataFrame
    only_in_right: pl.DataFrame
    mismatches: pl.DataFrame  # long format: keys..., column, left_value, right_value

    @property
    def mismatched_row_count(self) -> int:
        return self.mismatches.select(self.keys).unique().height if not self.mismatches.is_empty() else 0

    @property
    def is_reconciled(self) -> bool:
        return self.only_in_left.is_empty() and self.only_in_right.is_empty() and self.mismatches.is_empty()

    @property
    def match_rate(self) -> float:
        total = self.matched.height + self.mismatched_row_count + self.only_in_left.height + self.only_in_right.height
        return self.matched.height / total if total else 1.0

    def summary(self) -> str:
        lines = [
            f"Reconciliation on keys={self.keys}:",
            f"  matched:       {self.matched.height}",
            f"  mismatched:    {self.mismatched_row_count} row(s), {self.mismatches.height} field diff(s)",
            f"  only in left:  {self.only_in_left.height}",
            f"  only in right: {self.only_in_right.height}",
            f"  match rate:    {self.match_rate:.2%}",
        ]
        for label, frame in (
            ("mismatches", self.mismatches),
            ("only-in-left", self.only_in_left),
            ("only-in-right", self.only_in_right),
        ):
            if not frame.is_empty():
                lines.append(f"  sample {label}:")
                lines.append(textwrap.indent(str(frame.head(10)), "    "))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "is_reconciled": self.is_reconciled,
            "match_rate": self.match_rate,
            "matched": self.matched.height,
            "only_in_left": self.only_in_left.to_dicts(),
            "only_in_right": self.only_in_right.to_dicts(),
            "mismatches": self.mismatches.to_dicts(),
        }


def reconcile(
    left: pl.DataFrame,
    right: pl.DataFrame,
    keys: list[str],
    *,
    compare_columns: list[str] | None = None,
    ignore_columns: list[str] | None = None,
    tolerance: dict[str, float] | None = None,
    case_insensitive_columns: list[str] | None = None,
) -> ReconciliationResult:
    ignore = set(ignore_columns or [])
    tolerance = tolerance or {}
    case_insensitive = set(case_insensitive_columns or [])

    for k in keys:
        if k not in left.columns or k not in right.columns:
            raise ReconciliationSourceError(f"key column {k!r} missing from left and/or right dataset")
        if left.schema[k] != right.schema[k]:
            raise ReconciliationSourceError(
                f"key column {k!r} has mismatched dtypes: left={left.schema[k]} right={right.schema[k]}; "
                f"cast one side to match, e.g. left.with_columns(pl.col('{k}').cast(right.schema['{k}']))"
            )

    left = left.drop([c for c in ignore if c in left.columns])
    right = right.drop([c for c in ignore if c in right.columns])

    common_cols = [c for c in left.columns if c in right.columns and c not in keys]
    if compare_columns is not None:
        common_cols = [c for c in common_cols if c in compare_columns]

    left_marked = left.with_columns(pl.lit(True).alias("__in_left"))
    right_marked = right.with_columns(pl.lit(True).alias("__in_right"))
    joined = left_marked.join(right_marked, on=keys, how="full", suffix="_right", coalesce=True)
    joined = joined.with_columns(
        pl.col("__in_left").fill_null(False),
        pl.col("__in_right").fill_null(False),
    )

    only_in_left = (
        joined.filter(pl.col("__in_left") & ~pl.col("__in_right")).select(keys + common_cols)
    )
    only_in_right = (
        joined.filter(~pl.col("__in_left") & pl.col("__in_right"))
        .select(keys + [pl.col(f"{c}_right").alias(c) for c in common_cols])
    )
    both = joined.filter(pl.col("__in_left") & pl.col("__in_right"))

    match_exprs = []
    for c in common_cols:
        left_col, right_col = pl.col(c), pl.col(f"{c}_right")
        if c in tolerance:
            tol = tolerance[c]
            expr = (left_col.is_null() & right_col.is_null()) | ((left_col - right_col).abs() <= tol)
        elif c in case_insensitive:
            expr = left_col.str.to_lowercase().eq_missing(right_col.str.to_lowercase())
        else:
            expr = left_col.eq_missing(right_col)
        match_exprs.append(expr.alias(f"__match_{c}"))
    both = both.with_columns(match_exprs) if match_exprs else both

    matched = (
        both.filter(pl.all_horizontal([pl.col(f"__match_{c}") for c in common_cols]) if common_cols else pl.lit(True))
        .select(keys + common_cols)
    )
    mismatched_rows = (
        both.filter(~pl.all_horizontal([pl.col(f"__match_{c}") for c in common_cols]))
        if common_cols
        else both.clear()
    )

    mismatch_frames = []
    for c in common_cols:
        sub = (
            mismatched_rows.filter(~pl.col(f"__match_{c}"))
            .select(
                keys
                + [
                    pl.col(c).cast(pl.Utf8, strict=False).alias("left_value"),
                    pl.col(f"{c}_right").cast(pl.Utf8, strict=False).alias("right_value"),
                ]
            )
            .with_columns(pl.lit(c).alias("column"))
            .select(keys + ["column", "left_value", "right_value"])
        )
        if not sub.is_empty():
            mismatch_frames.append(sub)

    mismatches = (
        pl.concat(mismatch_frames, how="vertical_relaxed")
        if mismatch_frames
        else pl.DataFrame(schema={**{k: left.schema[k] for k in keys}, "column": pl.Utf8, "left_value": pl.Utf8, "right_value": pl.Utf8})
    )

    return ReconciliationResult(
        keys=keys, matched=matched, only_in_left=only_in_left, only_in_right=only_in_right, mismatches=mismatches
    )


class ReconciliationAgent(BaseAgent):
    name = "reconciliation"

    def compare(
        self,
        left: pl.DataFrame,
        right: pl.DataFrame,
        keys: list[str],
        *,
        compare_columns: list[str] | None = None,
        ignore_columns: list[str] | None = None,
        tolerance: dict[str, float] | None = None,
        case_insensitive_columns: list[str] | None = None,
    ) -> ReconciliationResult:
        with self.step("compare", detail=f"keys={keys} left={left.height} right={right.height}"):
            return reconcile(
                left,
                right,
                keys,
                compare_columns=compare_columns,
                ignore_columns=ignore_columns,
                tolerance=tolerance,
                case_insensitive_columns=case_insensitive_columns,
            )

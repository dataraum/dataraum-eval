"""The dimension prior library + the dry-run coverage read (DAT-885 / RFC 3 lane A2).

The priors are **data** (``dimension_priors.yaml``); this is the thin reader plus the
one thing that makes them checkable today: a dry run that answers *which dimensions
could this schema carry at all*, from table and column names alone — no pipeline, no
LLM, no engine.

**What the dry run is and is not.** It reads *structure*: does a schema expose the
entities a dimension's metrics need? That is a **capability** question, deliberately
weaker than the coverage map's *lit* (RFC 3 B2), which additionally requires a metric
to ground AND to grade within tolerance. Conflating the two is how a map starts lying,
so the vocabulary here is kept distinct on purpose:

    carryable  — every one of the dimension's allocation-free metrics has the
                 entities it names
    partial    — some metrics are supported, others name entities the schema lacks
    dark       — NO metric is supported. Availability decides, not required-entity
                 bookkeeping: a dimension that supports nothing must not read
                 `partial` just because it declared no required entities.

A *carryable* dimension is not a lit one. It means "the data could support this if the
engine recovers it", which is exactly what a staging-hub read should promise before
ingestion and no more.

**Matching is by name, and that is a stated limitation, not an oversight.** A prior's
entity resolves against a declared binding first (exact, authored) and falls back to
alias matching over table names. Name matching is not a semantic claim — the charter is
explicit that string matching is not a detector. It is honest here because the output is
a *proposal for a human to prune* (selection-first, RFC 0), never a graded verdict. When
frame induction consumes these priors (Lane B), the LLM does the semantic work and this
read stays what it is: a fast structural pre-check.

    uv run python -m calibration.dimension_priors --dataset clean
    uv run python -m calibration.dimension_priors --tables customers,orders,articles
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).parent.parent
PRIORS = Path(__file__).parent / "dimension_priors.yaml"

# The three dimensions the A1 chain lights. Supply/Capacity/Throughput are absent by
# decision, not oversight (RFC 3 B7 gates them on their generator families).
THIN_SLICE: tuple[str, ...] = ("demand", "offer", "capital")

CARRYABLE = "carryable"
PARTIAL = "partial"
DARK = "dark"


@dataclass(frozen=True)
class Entity:
    name: str
    required: bool
    aliases: tuple[str, ...]

    def matches(self, table: str) -> bool:
        """Does ``table`` look like this entity? Name-level only — see the module note."""
        candidate = table.lower().strip()
        names = {self.name, *self.aliases}
        for name in names:
            if candidate == name or candidate == f"{name}s":
                return True
            # a containing name (sales_order_lines ~ order_line) — the common ERP
            # prefixing, kept tight enough that `orders` does not match `order_line`
            if name in candidate and abs(len(candidate) - len(name)) <= 12:
                return True
        return False


@dataclass(frozen=True)
class Metric:
    id: str
    label: str
    grain: str
    allocation_free: bool
    needs_entities: tuple[str, ...]
    requires_allocation: bool = False


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    entities: tuple[Entity, ...]
    ladder: tuple[str, ...]
    metrics: tuple[Metric, ...]
    levers: tuple[str, ...]

    @property
    def required(self) -> tuple[str, ...]:
        return tuple(e.name for e in self.entities if e.required)


def load(path: Path = PRIORS) -> dict[str, Dimension]:
    """Parse the library. Pure (yaml → dataclasses), so Tier-1 exercises it."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    out: dict[str, Dimension] = {}
    for key, spec in (raw.get("dimensions") or {}).items():
        entities = tuple(
            Entity(
                name=e["name"],
                required=bool(e.get("required", False)),
                aliases=tuple(e.get("aliases") or ()),
            )
            for e in spec.get("entities") or []
        )
        metrics = tuple(
            Metric(
                id=m["id"],
                label=m["label"],
                grain=str(m.get("grain") or ""),
                allocation_free=bool(m.get("allocation_free", False)),
                # A metric that names no entities depends on its dimension's required
                # set — the common case, and why this defaults rather than erroring.
                needs_entities=tuple(m.get("needs_entities") or ()),
                requires_allocation=bool(m.get("requires_allocation", False)),
            )
            for m in spec.get("metrics") or []
        )
        out[key] = Dimension(
            key=key,
            label=spec.get("label", key),
            entities=entities,
            ladder=tuple(spec.get("ladder") or ()),
            metrics=metrics,
            levers=tuple(spec.get("levers") or ()),
        )
    return out


def bindings(path: Path = PRIORS) -> dict[str, dict[str, str]]:
    """vertical → {prior entity: schema table (or table.column)}."""
    raw: dict[str, Any] = yaml.safe_load(path.read_text()) or {}
    return {
        name: dict((spec or {}).get("entities") or {})
        for name, spec in (raw.get("bindings") or {}).items()
    }


@dataclass
class DimensionRead:
    dimension: str
    label: str
    status: str
    resolved: dict[str, str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    metrics_available: tuple[str, ...] = ()
    metrics_blocked: dict[str, tuple[str, ...]] = field(default_factory=dict)


def dry_run(
    tables: list[str],
    *,
    vertical: str | None = None,
    priors: dict[str, Dimension] | None = None,
    path: Path = PRIORS,
) -> list[DimensionRead]:
    """Which dimensions could this schema carry? Structure only (A2's exit criterion).

    ``vertical`` selects an authored binding, which wins over alias matching wherever it
    names an entity — an authored binding is a stated fact, alias matching is a guess.
    """
    priors = load(path) if priors is None else priors
    bound = bindings(path).get(vertical or "", {})
    table_set = [t.lower() for t in tables]

    out: list[DimensionRead] = []
    for key in THIN_SLICE:
        dim = priors.get(key)
        if dim is None:
            continue
        resolved: dict[str, str] = {}
        for entity in dim.entities:
            if entity.name in bound:
                # An authored binding may point at a column (products.product_group);
                # its table is what has to exist.
                target = bound[entity.name]
                if target.split(".")[0].lower() in table_set:
                    resolved[entity.name] = target
                continue
            hit = next((t for t in tables if entity.matches(t)), None)
            if hit is not None:
                resolved[entity.name] = hit

        missing_required = tuple(e for e in dim.required if e not in resolved)

        available: list[str] = []
        blocked: dict[str, tuple[str, ...]] = {}
        for metric in dim.metrics:
            needs = metric.needs_entities or dim.required
            gaps = tuple(n for n in needs if n not in resolved)
            if gaps:
                blocked[metric.id] = gaps
            elif metric.requires_allocation:
                # Structurally supportable, but the allocation object does not exist
                # yet (RFC 3 B5) — never counted as available, or the read would
                # promise a number nobody can reproduce.
                blocked[metric.id] = ("allocation_scheme",)
            else:
                available.append(metric.id)

        # A dimension supporting NOTHING is dark, whatever the required-entity
        # bookkeeping says. Capital deliberately marks no entity `required` (partial
        # coverage is normal there), which on a schema with no receivable, payable or
        # inventory at all — a motorsport corpus, say — made it read PARTIAL with zero
        # metrics available. That is the coverage-map lie in miniature: a status
        # implying "some of this works" when none of it does. Availability decides.
        if not available:
            status = DARK
        elif missing_required or blocked:
            status = PARTIAL
        else:
            status = CARRYABLE

        out.append(
            DimensionRead(
                dimension=key,
                label=dim.label,
                status=status,
                resolved=resolved,
                missing=missing_required,
                metrics_available=tuple(available),
                metrics_blocked=blocked,
            )
        )
    return out


def render(reads: list[DimensionRead], *, title: str) -> str:
    lines = [f"dimension dry run — {title}", ""]
    lines.append("  (carryable = the structure supports it; NOT 'lit', which additionally")
    lines.append("   requires a metric to ground AND grade within tolerance — RFC 3 B2)")
    lines.append("")
    for read in reads:
        lines.append(f"  {read.dimension:<10} {read.status.upper():<10} {read.label}")
        if read.resolved:
            pairs = ", ".join(f"{k}→{v}" for k, v in sorted(read.resolved.items()))
            lines.append(f"    resolved  {pairs}")
        if read.missing:
            lines.append(f"    MISSING   {', '.join(read.missing)}")
        if read.metrics_available:
            lines.append(f"    available {', '.join(read.metrics_available)}")
        for metric, gaps in sorted(read.metrics_blocked.items()):
            lines.append(f"    blocked   {metric} (needs {', '.join(gaps)})")
        lines.append("")
    return "\n".join(lines)


def _dataset_tables(dataset: str) -> list[str]:
    """Table names for a generated corpus, from its CSVs — no pipeline needed."""
    data_dir = EVAL_ROOT / "data" / dataset
    if not data_dir.exists():
        raise SystemExit(f"no generated data at {data_dir}")
    return sorted(p.stem for p in data_dir.glob("*.csv"))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="dimension prior dry run (DAT-885)")
    parser.add_argument("--dataset", help="a generated corpus under data/")
    parser.add_argument("--tables", help="comma-separated table names (any schema)")
    parser.add_argument("--vertical", help="use this authored binding (e.g. finance)")
    args = parser.parse_args()

    if args.tables:
        tables = [t.strip() for t in args.tables.split(",") if t.strip()]
        title = f"{len(tables)} declared tables"
    elif args.dataset:
        tables = _dataset_tables(args.dataset)
        title = f"data/{args.dataset} ({len(tables)} tables)"
    else:
        raise SystemExit("pass --dataset or --tables")

    print(render(dry_run(tables, vertical=args.vertical), title=title))


if __name__ == "__main__":
    main()

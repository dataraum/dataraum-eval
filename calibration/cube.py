"""The execution cube — per-oracle dataset/stage declarations + the planner (DAT-860).

The dependency direction, ruled 2026-07-22 (Philipp): "An eval/test must be bound to a
dataset, the position in the flow defines how much cache it can re-use, so the caching
is serving the dataset that serves the eval." Eval → dataset → cache, never the other
way around: the cache (DAT-861) is run economy for oracle iteration and downstream-stage
reuse, NEVER a graded surface — a cached stage pins one draw of the LLM, and grading
engine behaviour needs fresh draws (epochs + reducer, DAT-863). The retired 45-cell
fixture lane died on exactly this confusion.

Slice 1 is declaration + planner in REPORT mode: nothing executes differently yet —
``calibration.run`` is untouched (DAT-863 evolves it). What this slice buys:

* every Tier-3 oracle module carries an explicit ``pytestmark = cube.needs(...)``
  naming its vertical, the dataset(s) it binds to, and the deepest pipeline stage
  whose output it consumes (``from_stage``);
* the declaration is ENFORCED (unit/test_cube.py: an undeclared Tier-3 module fails
  the suite), so new oracles are born declarative;
* ``python -m calibration.cube -s <datasets>`` prints the minimal (dataset × stage)
  cells a grade requires — the plan the staged cache (DAT-861) and the executor
  (DAT-863) will consume.

``from_stage`` semantics: the deepest stage of the pipeline chain
(raw → add_source → begin_session → operating_model) whose output the oracle reads.
``raw`` = generated data files only, no pipeline. Deeper than needed is safe but wastes
the cube's value; shallower under-materializes and grades missing rows as engine misses
— when in doubt declare deep and tighten with evidence.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# The pipeline chain, shallow → deep. Order IS the contract: materializing a stage
# passes through every shallower stage, so one run to `depth` can snapshot every
# consumed cell on the way (the DAT-861 cache's write path).
STAGES: tuple[str, ...] = ("raw", "add_source", "begin_session", "operating_model")

TIER3_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Needs:
    """One oracle module's declared needs — the cube cell(s) it consumes.

    ``datasets`` is None for "any dataset of the vertical" (bound at plan time to the
    dataset under grade) or an explicit tuple for a dataset-specific oracle (e.g. the
    stockflow oracles, hardwired to ``detection-stockflow-v1``). ``baseline`` names
    datasets ADDITIONALLY consumed at the same stage (the clean-baseline reads:
    ``clean_pipeline_scores``, ``score_deltas``, ``clean_intent_readiness``).
    ``version`` is the oracle version (DAT-862): bump on any verdict-changing change
    to the module — threshold, vocabulary, assertion shape — so stored verdicts are
    never silently compared across different oracles.
    """

    vertical: str
    datasets: tuple[str, ...] | None
    from_stage: str
    baseline: tuple[str, ...] = ()
    version: int = 1

    def binds(self, dataset: str) -> bool:
        return self.datasets is None or dataset in self.datasets


def needs(
    *,
    vertical: str,
    dataset: str | tuple[str, ...],
    from_stage: str,
    baseline: tuple[str, ...] = (),
    version: int = 1,
) -> pytest.MarkDecorator:
    """The per-oracle declaration (DAT-860): ``pytestmark = cube.needs(...)``.

    Returns a pytest marker so the declaration rides on collected items too; the
    registry reads it back off the module's ``pytestmark``.
    """
    if from_stage not in STAGES:
        raise ValueError(f"from_stage {from_stage!r} not in {STAGES}")
    datasets: tuple[str, ...] | None
    if dataset == "*":
        datasets = None
    elif isinstance(dataset, str):
        datasets = (dataset,)
    else:
        datasets = tuple(dataset)
        if not datasets:
            raise ValueError("dataset tuple must not be empty — use '*' for any")
    spec = Needs(
        vertical=vertical,
        datasets=datasets,
        from_stage=from_stage,
        baseline=tuple(baseline),
        version=version,
    )
    return pytest.mark.needs(spec=spec)


def tier3_modules() -> list[str]:
    """Basenames of every Tier-3 oracle module (``calibration/test_*.py``)."""
    return sorted(p.stem for p in TIER3_DIR.glob("test_*.py"))


def _needs_from_module(module_name: str) -> Needs | None:
    mod = importlib.import_module(f"calibration.{module_name}")
    marks = getattr(mod, "pytestmark", None)
    if marks is None:
        return None
    if not isinstance(marks, list):
        marks = [marks]
    for m in marks:
        mark = getattr(m, "mark", m)  # MarkDecorator → Mark
        if getattr(mark, "name", None) == "needs":
            spec: Needs = mark.kwargs["spec"]
            return spec
    return None


def registry() -> dict[str, Needs]:
    """module basename → its declared Needs, for every declared Tier-3 module."""
    out: dict[str, Needs] = {}
    for name in tier3_modules():
        spec = _needs_from_module(name)
        if spec is not None:
            out[name] = spec
    return out


def undeclared() -> list[str]:
    """Tier-3 modules with NO cube declaration — enforced empty by unit/test_cube.py."""
    return [name for name in tier3_modules() if _needs_from_module(name) is None]


# ---------------------------------------------------------------------------
# The planner (report mode)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Cell:
    """One (dataset × stage) artifact — the cache's unit (DAT-861)."""

    dataset: str
    stage: str


@dataclass(frozen=True)
class Binding:
    """One oracle bound to the cell(s) it consumes for one graded dataset."""

    module: str
    cell: Cell
    baseline_cells: tuple[Cell, ...] = ()


@dataclass
class Plan:
    """The minimal materialization a grade of ``requested`` requires."""

    vertical: str
    requested: tuple[str, ...]
    bindings: list[Binding] = field(default_factory=list)
    undeclared: tuple[str, ...] = ()

    @property
    def cells(self) -> list[Cell]:
        """Every distinct consumed cell, baselines included — the cache's write list."""
        seen = {b.cell for b in self.bindings}
        seen.update(c for b in self.bindings for c in b.baseline_cells)
        return sorted(seen)

    @property
    def depth(self) -> dict[str, str]:
        """dataset → deepest stage any bound oracle consumes: the work to run.

        Shallower consumed cells fall out on the way (STAGES order); a dataset whose
        depth is ``raw`` needs generation only, no pipeline.
        """
        deepest: dict[str, int] = {}
        for cell in self.cells:
            rank = STAGES.index(cell.stage)
            if rank > deepest.get(cell.dataset, -1):
                deepest[cell.dataset] = rank
        return {ds: STAGES[rank] for ds, rank in sorted(deepest.items())}

    @property
    def pulled_baselines(self) -> list[str]:
        """Datasets required only as a baseline, not requested themselves."""
        baseline_ds = {c.dataset for b in self.bindings for c in b.baseline_cells}
        return sorted(baseline_ds - set(self.requested))

    def render(self) -> str:
        lines = [f"cube plan — vertical={self.vertical}  datasets={', '.join(self.requested)}"]
        lines.append("\nwork per dataset (deepest consumed stage — shallower cells fall out):")
        for ds, stage in self.depth.items():
            n = sum(1 for b in self.bindings if b.cell.dataset == ds)
            lines.append(f"  {ds:<36} → {stage:<16} ({n} oracle(s) bound)")
        for ds in self.requested:
            if ds not in self.depth:
                lines.append(f"  {ds:<36} → NOTHING BOUND (no oracle binds this dataset)")
        if self.pulled_baselines:
            lines.append(
                f"\nbaselines pulled in (consumed, not requested): "
                f"{', '.join(self.pulled_baselines)}"
            )
        lines.append("\noracle → cell:")
        for b in sorted(self.bindings, key=lambda b: (b.cell, b.module)):
            extra = ""
            if b.baseline_cells:
                extra = "  (+ " + ", ".join(
                    f"{c.dataset}@{c.stage}" for c in b.baseline_cells
                ) + ")"
            lines.append(f"  {b.cell.dataset}@{b.cell.stage:<16} {b.module}{extra}")
        if self.undeclared:
            lines.append(
                f"\n⚠ UNDECLARED Tier-3 modules (not planned, not cacheable): "
                f"{', '.join(self.undeclared)}"
            )
        return "\n".join(lines)


def plan(
    datasets: list[str],
    *,
    vertical: str = "finance",
    reg: dict[str, Needs] | None = None,
) -> Plan:
    """Bind every declared oracle of ``vertical`` to the requested datasets.

    Report mode (slice 1): computes the minimal (dataset × stage) set — it does not
    execute anything. One cube per vertical (DAT-860): oracles declared for another
    vertical never bind.
    """
    reg = registry() if reg is None else reg
    result = Plan(vertical=vertical, requested=tuple(datasets), undeclared=tuple(undeclared()))
    for ds in datasets:
        for module, spec in sorted(reg.items()):
            if spec.vertical != vertical or not spec.binds(ds):
                continue
            result.bindings.append(
                Binding(
                    module=module,
                    cell=Cell(dataset=ds, stage=spec.from_stage),
                    baseline_cells=tuple(
                        Cell(dataset=b, stage=spec.from_stage)
                        for b in spec.baseline
                        if b != ds
                    ),
                )
            )
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="cube planner — report mode (DAT-860)")
    parser.add_argument("-s", "--datasets", required=True, help="comma-separated dataset names")
    parser.add_argument("--vertical", default="finance")
    args = parser.parse_args()
    names = [s.strip() for s in args.datasets.split(",") if s.strip()]
    print(plan(names, vertical=args.vertical).render())


if __name__ == "__main__":
    main()

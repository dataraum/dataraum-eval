"""DAT-762 attempt 3 — the frame, written without reading the answer key.

Provenance of this file, because it is the whole point of it: nothing here was
derived from `ground_truth.csv`, from `exact_candidates()["meaningful"]`, from
`verify_rwd.py`, or from `GATE.md`. The origin menu below was built by reading
the nine RWD tables and their exact pairs with the label stripped at the loader,
asking only "what mechanisms in this data can fix B once A is fixed?".

Design rules this file follows, each one a defect of the previous attempt:

1. ORIGIN NAMES ARE MECHANISMS, NOT VERDICTS. Attempt 2's menu said "NEAR-KEY
   ARTIFACT", "DEGENERATE TARGET", "THIN EVIDENCE". Those names are the answer
   smuggled into the question: "artifact" pre-judges the cell before the judge
   reads a number. Here an origin is named for how it works ("A identifies the
   row itself"), and whether that counts as designed is left to the judge --
   which is the only thing we are actually asking it.

2. NO DIRECTION ON ANY NUMBER. Attempt 2 said "The closer that is to one row per
   value, the less this dependency means." That belief is false on this very
   benchmark: `key1` in dblp10k is 89.2% unique per row and still plausibly a
   designed key -> attribute rule, while `ClaimNumber` is 100.0% unique and
   arguably the same thing. A frame that tells the judge which way to read a
   ratio is a frame that grades itself. Every number below is stated flat.

3. NO COLUMN-KIND TASTE. No line here says a timestamp, id, code, name, or free
   text is good or bad evidence. Mechanisms are described; column kinds are never
   ranked.

4. EVERY PAIR RENDERS. No branching that drops a pair to bare evidence. The three
   cardinality cases are all handled, including the one that contradicts the
   premise (see MEASURED, below), and the zero-row edge.

frame() is pure over `Facts` -- it never reloads a table, so it cannot see
anything the judge is not also shown.
"""

from __future__ import annotations

from judge2 import Facts

# --------------------------------------------------------------- derived facts


def _direction_fact(f: Facts) -> str:
    """What A's and B's distinct counts entail about the reverse dependency.

    Given A -> B holds on the compared rows:
      |B| <  |A|  =>  some B value carries >1 A value, so B -> A fails.
      |B| == |A|  =>  the map is a bijection on these rows, so B -> A holds too.
      |B| >  |A|  =>  arithmetically impossible under the premise. Stated, not
                      hidden: the judge is entitled to notice that the evidence
                      and the premise disagree, and the last origin covers it.
    """
    na, nb = f.a.distinct, f.b.distinct
    if na == 0 or nb == 0:
        return (
            f"* One of the two columns has no non-null values among the rows "
            f"compared, so there is nothing to compare."
        )
    if nb < na:
        return (
            f"* Because `{f.b.name}` takes fewer distinct values ({nb:,}) than "
            f"`{f.a.name}` ({na:,}), at least one `{f.b.name}` value occurs with "
            f"more than one `{f.a.name}` value: the dependency does not run in "
            f"reverse on these rows."
        )
    if nb == na:
        return (
            f"* `{f.a.name}` and `{f.b.name}` take the same number of distinct "
            f"values ({na:,}) on these rows, so the mapping between them is "
            f"one-to-one and holds in both directions here."
        )
    return (
        f"* `{f.b.name}` takes more distinct values ({nb:,}) than `{f.a.name}` "
        f"({na:,}) on the rows compared. A dependency that held with no "
        f"exceptions on exactly these rows could not do that, so the premise and "
        f"the counts do not agree for this pair."
    )


def _measured(f: Facts) -> str:
    """Numbers derivable from f that evidence_block() does not already render.

    evidence_block gives A's distinct count, A's share of rows, and A's rows per
    value. It gives neither the same three for B nor the relation between the two
    columns' cardinalities. Those are supplied here and nothing else is repeated.
    """
    lines = [_direction_fact(f)]
    if f.b.distinct:
        rows_per_b = f.n_rows / f.b.distinct
        b_key_frac = f.b.distinct / f.n_rows if f.n_rows else 0.0
        lines.append(
            f"* `{f.b.name}` takes {f.b.distinct:,} distinct values over the "
            f"{f.n_rows:,} rows compared ({b_key_frac:.1%} — {rows_per_b:.1f} "
            f"rows per `{f.b.name}` value on average)."
        )
    lines.append(
        f"* The rows compared are the rows where `{f.a.name}` and `{f.b.name}` "
        f"are both present. Rows excluded by that condition are not described by "
        f"this dependency one way or the other."
    )
    return "\n".join(lines)


# --------------------------------------------------------------- the menu

_ORIGINS = """\
* A NAMES SOMETHING THE TABLE DESCRIBES MORE THAN ONCE — `{a}` identifies a \
thing that recurs across rows, and `{b}` records a property of that thing. The \
value of `{b}` is fixed because the thing is.

* A IDENTIFIES THE ROW ITSELF — `{a}` picks out one row, or close to it. Every \
column in the table is then fixed once `{a}` is fixed, and `{b}` is not being \
singled out. Bearing on this: `{a}`'s distinct count against the row count, above.

* A AND B ARE TWO RENDERINGS OF ONE FACT — the two columns carry the same \
underlying content in different form: a value and its label, an abbreviation and \
its expansion, one scale and another. The mapping is a naming or encoding \
convention. Bearing on this: the two distinct counts, and the sample values above.

* B IS PART OF A, OR COMPUTED FROM A — `{b}` can be read out of `{a}`'s value by \
splitting, parsing, or arithmetic on it, without consulting anything else. \
Bearing on this: whether `{b}`'s sample values appear inside `{a}`'s, above.

* A STANDS IN FOR SOMETHING IT DOES NOT NAME — `{a}` is not the identifier of the \
thing `{b}` is a property of, but sits one-to-one with that thing across these \
rows, so `{b}` follows through it rather than from `{a}`. Bearing on this: what \
else is in the table — {cols_hint}.

* A RULE OUTSIDE THIS DATABASE TIES THEM — the relation is a fact of the domain \
rather than something this schema declares: containment, jurisdiction, taxonomy, \
a published standard. It would hold in any table carrying these two columns.

* B IS NEARLY THE SAME VALUE THROUGHOUT — across the rows compared, `{b}` takes \
few distinct values, or one of its values covers most of the rows. Bearing on \
this: `{b}`'s distinct count and its most common value's share, above.

* THE ROWS COMPARED ARE FEW, OR ARE A PARTICULAR SUBSET — the dependency holds \
across the rows that were compared and says nothing about the rest. Bearing on \
this: the count of rows compared, above.

* A REGULARITY OF THE POPULATION THAT WAS LOADED — the rows here line up with no \
exception, and no rule requires them to; another draw of rows collected the same \
way need not. Nothing about the number of rows need be unusual for this.

* ONE SIDE CARRIES A PLACEHOLDER — among the values of `{a}` or `{b}` is a token \
standing for absent, unknown, or not-applicable rather than naming a thing. Rows \
under such a token are grouped by it like any other value. Bearing on this: the \
most frequent values listed above.

* YOU CANNOT TELL FROM THIS EVIDENCE — the facts above are consistent with more \
than one of the origins above and do not separate them. This is a real answer and \
not a failure to produce one: say so, and report confidence "low", rather than \
choosing the most plausible-sounding story at a confidence the evidence does not \
support."""


def _cols_hint(f: Facts, limit: int = 6) -> str:
    """Name the table's other columns, neutrally, so the proxy origin is checkable.

    evidence_block lists all columns; this points at the ones that are not A or B
    without re-listing the whole set. No column kind is characterised.
    """
    others = [c for c in f.table_cols if c not in (f.a.name, f.b.name)]
    if not others:
        return "this table has no columns besides these two"
    shown = ", ".join(f"`{c}`" for c in others[:limit])
    if len(others) > limit:
        return f"the table's other columns include {shown}, and {len(others) - limit:,} more"
    return f"the table's other columns are {shown}"


# --------------------------------------------------------------- frame


def frame(f: Facts) -> str:
    """The origins that can produce an exactly-holding FD, and the facts in play.

    Appended after evidence_block(f), which has already rendered the table's
    columns, both column profiles with sample values, and A's cardinality. This
    adds: the claim under judgement, the numbers evidence_block leaves out, and
    the menu of origins. It never says which way a number points.
    """
    a, b = f.a.name, f.b.name
    measured = _measured(f)
    origins = _ORIGINS.format(a=a, b=b, cols_hint=_cols_hint(f))
    return f"""The claim under judgement: `{a}` -> `{b}` holds with no exceptions \
across the {f.n_rows:,} rows compared above — every row with the same `{a}` value \
has the same `{b}` value. That it holds is the premise; the question is what makes \
it hold.

MEASURED, in addition to the profile above:

{measured}

ORIGINS. Each of the following can produce a dependency that holds with no \
exceptions. They are not in any order, and more than one can be true of the same \
pair. Work out which of them accounts for THIS pair, then answer the question the \
system prompt asks.

{origins}"""

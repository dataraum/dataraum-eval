"""DAT-757 channel-ablation — the frozen cell inventory (see PROTOCOL.md).

45 cells over the three folded RelBench OBTs (+2 constructed cross-view cells).
Truth labels are pre-registered semantic judgments with one-line justifications;
frozen before any grading. Column names refer to the OBTs built by
probe_fold_grade.build_obt with the same SPECS.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    id: str
    klass: str
    dataset: str  # rel-f1 | rel-hm | rel-salt | constructed:<dataset>
    a: str
    b: str
    truth: str  # MERGE | HIERARCHY | ROLE | REJECT
    why: str  # pre-registered justification (HIERARCHY direction is a -> b)


CELLS: list[Cell] = [
    # A — true aliases (exact code<->name / id<->name bijections) -> MERGE
    Cell("A1", "A-true-alias", "rel-hm", "article__colour_group_code", "article__colour_group_name",
         "MERGE", "exact code<->name bijection, one colour-group identity"),
    Cell("A2", "A-true-alias", "rel-hm", "article__index_code", "article__index_name",
         "MERGE", "exact code<->name bijection"),
    Cell("A3", "A-true-alias", "rel-hm", "article__garment_group_no", "article__garment_group_name",
         "MERGE", "exact code<->name bijection"),
    Cell("A4", "A-true-alias", "rel-hm", "article__section_no", "article__section_name",
         "MERGE", "exact code<->name bijection"),
    Cell("A5", "A-true-alias", "rel-f1", "constructor__constructorRef", "constructor__name",
         "MERGE", "two name-forms of the constructor identity"),
    Cell("A6", "A-true-alias", "rel-f1", "race__circuitId", "circuit__name",
         "MERGE", "id<->unique name of the same circuit entity"),
    # B — dirty aliases (same concept, few colliding rows) -> MERGE
    Cell("B1", "B-dirty-alias", "rel-hm", "article__product_type_no", "article__product_type_name",
         "MERGE", "code<->name with k=9 name collisions in 190k rows — still one concept"),
    Cell("B2", "B-dirty-alias", "rel-f1", "date", "race__date",
         "MERGE", "pre-existing denormalized copy of the same date value"),
    # P — proxy bijections: statistically MERGE, semantically an attribute edge
    Cell("P1", "P-proxy-bijection", "rel-f1", "raceId", "date",
         "HIERARCHY", "date is an attribute of the race; bijective by accident of history — an id is not a date"),
    Cell("P2", "P-proxy-bijection", "rel-salt", "SALESDOCUMENT", "CREATIONTIMESTAMP",
         "HIERARCHY", "timestamp is an attribute of the document, not its identity"),
    # C — role-playing near-copies -> ROLE
    Cell("C1", "C-role", "rel-salt", "BILLTOPARTY", "PAYERPARTY",
         "ROLE", "distinct SAP partner roles; disagreements are business-systematic"),
    Cell("C2", "C-role", "rel-salt", "soldto_addr__COUNTRY", "billto_addr__COUNTRY",
         "ROLE", "same geo concept via two party roles"),
    Cell("C3", "C-role", "rel-salt", "billto_addr__REGION", "payer_addr__REGION",
         "ROLE", "same geo concept via two party roles"),
    Cell("C4", "C-role", "rel-salt", "ITEMINCOTERMSCLASSIFICATION", "doc__HEADERINCOTERMSCLASSIFICATION",
         "ROLE", "item-level override of the header value — same concept, two grains"),
    Cell("C5", "C-role", "rel-f1", "grid", "position",
         "ROLE", "start vs finish position — same concept, two temporal roles"),
    # D — quasi-identifiers -> REJECT
    Cell("D1", "D-quasi-identifier", "rel-f1", "driver__dob", "driver__surname",
         "REJECT", "birthday collisions are rare among 857 drivers; dob is not an identity"),
    Cell("D2", "D-quasi-identifier", "rel-f1", "driver__dob", "driver__nationality",
         "REJECT", "same quasi-identifier artifact"),
    Cell("D3", "D-quasi-identifier", "rel-hm", "customer__postal_code", "customer__club_member_status",
         "REJECT", "postal code nearly identifies the customer; not a dimension edge"),
    Cell("D4", "D-quasi-identifier", "rel-f1", "driver__surname", "driver__nationality",
         "REJECT", "surnames cluster by nationality — real signal, not a groupable dimension edge"),
    # E — free-text determinants -> REJECT
    Cell("E1", "E-free-text", "rel-hm", "article__detail_desc", "article__garment_group_name",
         "REJECT", "a description is not a dimension level, however well it predicts"),
    Cell("E2", "E-free-text", "rel-hm", "article__detail_desc", "article__index_group_name",
         "REJECT", "same free-text artifact"),
    # F — dirty-true hierarchy edges -> HIERARCHY (a -> b)
    Cell("F1", "F-dirty-hierarchy", "rel-hm", "article__product_code", "article__product_type_name",
         "HIERARCHY", "real merchandising hierarchy with exceptions (g3 ~0.008)"),
    Cell("F2", "F-dirty-hierarchy", "rel-hm", "article__product_code", "article__department_name",
         "HIERARCHY", "real hierarchy with exceptions"),
    Cell("F3", "F-dirty-hierarchy", "rel-hm", "article__department_name", "article__garment_group_name",
         "HIERARCHY", "departments group into garment groups, few exceptions"),
    Cell("F4", "F-dirty-hierarchy", "rel-salt", "SHIPPINGPOINT", "PLANT",
         "HIERARCHY", "SAP org: shipping points belong to plants"),
    Cell("F5", "F-dirty-hierarchy", "rel-f1", "circuit__location", "circuit__alt",
         "HIERARCHY", "altitude is an attribute of the circuit's location (two same-city exceptions)"),
    # G — grain quasi-keys
    Cell("G1", "G-grain", "rel-salt", "SALESDOCUMENT", "BILLTOPARTY",
         "HIERARCHY", "partner roles are document-grain attributes (rare item-level overrides)"),
    Cell("G2", "G-grain", "rel-salt", "SALESDOCUMENT", "PLANT",
         "HIERARCHY", "plant is document-grain with item overrides"),
    Cell("G3", "G-grain", "rel-salt", "doc__CREATIONTIMESTAMP", "doc__SALESGROUP",
         "REJECT", "a timestamp is a proxy determinant, not a grouping key"),
    # H — weak-but-true org edges -> HIERARCHY
    Cell("H1", "H-weak-true", "rel-salt", "SOLDTOPARTY", "doc__SALESOFFICE",
         "HIERARCHY", "customers are assigned to sales offices (lambda 0.66)"),
    Cell("H2", "H-weak-true", "rel-salt", "PLANT", "doc__SALESORGANIZATION",
         "HIERARCHY", "plants belong to sales organizations (g3 0.00026)"),
    # I — vacuous skew -> REJECT
    Cell("I1", "I-vacuous-skew", "rel-salt", "SALESDOCUMENTITEM", "doc__DISTRIBUTIONCHANNEL",
         "REJECT", "g3 equals the minority mass (lambda=0): no reduction over the majority baseline"),
    Cell("I2", "I-vacuous-skew", "rel-salt", "PLANT", "doc__DISTRIBUTIONCHANNEL",
         "REJECT", "lambda=0 vacuous assert"),
    Cell("I3", "I-vacuous-skew", "rel-salt", "billto_addr__COUNTRY", "doc__SALESOFFICE",
         "REJECT", "lambda=0.08 — nearly no reduction over baseline"),
    # J — true-FK sanity positives -> HIERARCHY (regression guard)
    Cell("J1", "J-true-fk", "rel-f1", "raceId", "race__year",
         "HIERARCHY", "exact FK-derived fold edge"),
    Cell("J2", "J-true-fk", "rel-f1", "driverId", "driver__nationality",
         "HIERARCHY", "exact FK-derived fold edge"),
    Cell("J3", "J-true-fk", "rel-f1", "circuit__location", "circuit__country",
         "HIERARCHY", "exact geo hierarchy"),
    Cell("J4", "J-true-fk", "rel-hm", "article_id", "article__product_group_name",
         "HIERARCHY", "exact FK-derived fold edge"),
    Cell("J5", "J-true-fk", "rel-salt", "SALESDOCUMENT", "doc__SALESORGANIZATION",
         "HIERARCHY", "exact FK-derived fold edge"),
    # M — measure-derived -> REJECT
    Cell("M1", "M-measure-derived", "rel-f1", "position", "points",
         "REJECT", "points are computed from position by era scoring tables — measure, not dimension"),
    # K — disjoint-value same-concept (constructed cross-view) -> MERGE
    Cell("K1", "K-disjoint-conform", "constructed:rel-salt", "region_view1", "region_view2",
         "MERGE", "same REGION attribute partitioned by country into two views; value sets disjoint"),
    Cell("K2", "K-disjoint-conform", "constructed:rel-f1", "driver__nationality", "circuit__country",
         "MERGE", "demonyms vs country names — both conform to a Country dimension via a mapping (SOFT label)"),
    # L — false friends -> REJECT
    Cell("L1", "L-false-friend", "rel-salt", "doc__SALESOFFICE", "doc__SALESGROUP",
         "REJECT", "overlapping numeric code domains, different org concepts"),
    Cell("L2", "L-false-friend", "rel-hm", "customer__FN", "customer__Active",
         "REJECT", "both {1,null} flags, different meanings"),
    Cell("L3", "L-false-friend", "rel-f1", "number", "grid",
         "REJECT", "car number vs grid slot — overlapping integers, different concepts"),
]

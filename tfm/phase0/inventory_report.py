"""DAT-742 Phase 0: merge per-engine inventory JSONs into the engine x read-out matrix."""

import json

from common import INVENTORY_DIR, READ_OUTS

ENGINES = ["tabpfn", "tabicl", "tabfm"]
GLYPH = {"ok": "OK", "missing": "—", "error": "ERR"}


def main() -> None:
    data = {}
    for engine in ENGINES:
        path = INVENTORY_DIR / f"{engine}.json"
        if not path.exists():
            print(f"!! no inventory for {engine} ({path})")
            continue
        rows = json.loads(path.read_text())["rows"]
        data[engine] = {r["read_out"]: r for r in rows}

    col = max(len(e) for e in ENGINES) + 2
    header = "read_out".ljust(22) + "".join(e.ljust(col + 6) for e in data)
    print(header)
    print("-" * len(header))
    for ro in READ_OUTS:
        line = ro.ljust(22)
        for engine in data:
            r = data[engine].get(ro)
            cell = f"{GLYPH.get(r['status'], '?')} {r['seconds']}s" if r else "?"
            line += cell.ljust(col + 6)
        print(line)

    print("\nnotes:")
    for engine in data:
        for r in data[engine].values():
            print(f"  {engine}.{r['read_out']}: [{r['status']}] {r['note']}")


if __name__ == "__main__":
    main()

"""Before/after diff of ``clean_bands.yaml`` across a rebaseline (DAT-826).

A rebaseline is not a regression hunt — the point is to SEE what moved and be able
to say why, not to check that nothing did. Prints per detector: how many keys the
old and new artifacts carry, and the keys that appeared, vanished, or shifted band.

    uv run python scripts/probes/dat826-rebaseline/diff_bands.py <old.yaml> [new.yaml]
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

EVAL_ROOT = Path(__file__).resolve().parents[3]
NEW_DEFAULT = EVAL_ROOT / "calibration" / "clean_bands.yaml"


def _flat(doc: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (grain, key): band
        for grain, entries in (doc.get("bands") or {}).items()
        for key, band in entries.items()
    }


def _detector(key: str) -> str:
    return key.rsplit(":", 1)[-1]


def main(old_path: str, new_path: str) -> None:
    old_doc = yaml.safe_load(Path(old_path).read_text())
    new_doc = yaml.safe_load(Path(new_path).read_text())
    old, new = _flat(old_doc), _flat(new_doc)

    print(f"old provenance: {old_doc.get('provenance', {}).get('seeds')} "
          f"{old_doc.get('provenance', {}).get('date')}")
    print(f"new provenance: {new_doc.get('provenance', {}).get('seeds')} "
          f"{new_doc.get('provenance', {}).get('date')}")

    dets = sorted({_detector(k) for _, k in old} | {_detector(k) for _, k in new})
    print(f"\n{'detector':<26} {'old':>5} {'new':>5}   delta")
    for det in dets:
        o = sum(1 for _, k in old if _detector(k) == det)
        n = sum(1 for _, k in new if _detector(k) == det)
        mark = "" if o == n else ("  <-- GONE" if n == 0 else "  <--")
        print(f"{det:<26} {o:>5} {n:>5}   {n - o:+d}{mark}")

    vanished = sorted(set(old) - set(new))
    appeared = sorted(set(new) - set(old))
    print(f"\n{len(vanished)} key(s) dropped below the 0.1 floor (or stopped emitting):")
    for grain, key in vanished:
        print(f"  [{grain}] {key}: was [{old[(grain, key)]['min']:.3f}, "
              f"{old[(grain, key)]['max']:.3f}] seen {old[(grain, key)]['seen']}x")
    print(f"\n{len(appeared)} key(s) newly above the floor:")
    for grain, key in appeared:
        print(f"  [{grain}] {key}: now [{new[(grain, key)]['min']:.3f}, "
              f"{new[(grain, key)]['max']:.3f}] seen {new[(grain, key)]['seen']}x")

    moved = [
        (g, k) for g, k in sorted(set(old) & set(new))
        if abs(float(old[(g, k)]["max"]) - float(new[(g, k)]["max"])) > 1e-9
        or abs(float(old[(g, k)]["min"]) - float(new[(g, k)]["min"])) > 1e-9
    ]
    print(f"\n{len(moved)} key(s) present in both but with a shifted band:")
    for grain, key in moved:
        o, n = old[(grain, key)], new[(grain, key)]
        print(f"  [{grain}] {key}: [{o['min']:.3f}, {o['max']:.3f}] "
              f"→ [{n['min']:.3f}, {n['max']:.3f}]")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("old_path")
    p.add_argument("new_path", nargs="?", default=str(NEW_DEFAULT))
    main(**vars(p.parse_args()))

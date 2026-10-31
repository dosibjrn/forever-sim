#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rulesets.forever.items.wowhead_capture_import import import_adaptive_capture
from src.rulesets.forever.items.catalogue import ItemCatalogue


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the offline Forever item catalogue from an adaptive Wowhead capture directory")
    ap.add_argument("capture_dir", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "forever" / "catalogue" / "items.sqlite")
    ap.add_argument("--summary", type=Path, default=None)
    args = ap.parse_args()

    summary = import_adaptive_capture(args.capture_dir, args.out)
    payload = summary.as_dict()
    with ItemCatalogue(args.out) as cat:
        model = cat.availability_floor_model()
    if model is not None:
        payload["availability_floor_model"] = {
            "degree": model.degree,
            "quadratic_a": model.quadratic_a,
            "linear_b": model.linear_b,
            "intercept_c": model.intercept_c,
            "rmse": model.rmse,
            "lower_sigma": model.lower_sigma,
            "observed_sample_count": model.observed_sample_count,
            "retained_sample_count": model.retained_sample_count,
            "excluded_low_outliers": model.excluded_low_outliers,
            "source_catalogue_hash": model.source_catalogue_hash,
        }
    summary_path = args.summary or args.out.with_suffix(".manifest.json")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built {summary.canonical_items} canonical items / {summary.class_eligibility_rows} class links "
        f"-> {args.out}\n"
        f"req-level observed={summary.observed_required_level} inferred={summary.inferred_required_level} "
        f"unresolved={summary.unresolved_required_level}\n"
        f"catalogue={summary.catalogue_hash}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

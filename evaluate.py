"""Compare saved extraction JSON files with the labelled reports.

Example (no model/API calls):
    python evaluate.py extracted

The directory should contain files named like gold/report_01.json.
"""

import argparse
import json
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parent
GOLD_DIR = ROOT / "gold"
COMMA_NUMBER = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3})(?:\.\d+)?$"
)


def name_key(value):
    return " ".join(str(value or "").casefold().split())


NAME_ALIASES = {
    "cholesterol - ldl": "ldl cholesterol",
    "glucose - pp": "postprandial glucose",
    "cholesterol - total": "total cholesterol",
    "s. cholesterol": "total cholesterol",
    "cholesterol - hdl": "hdl cholesterol",
    "hdl-c": "hdl cholesterol",
    "cholesterol - vldl": "vldl cholesterol",
    "vldl": "vldl cholesterol",
    "tg": "triglycerides",
    "tc/hdl ratio": "cholesterol/hdl ratio",
    "chol/hdl": "cholesterol/hdl ratio",
    "total cholesterol / hdl ratio": "cholesterol/hdl ratio",
    "ldl-c (direct)": "ldl cholesterol (direct)",
    "aspartate aminotransferase": "ast",
    "aspartate aminotransferase (ast)": "ast",
    "alanine aminotransferase": "alt",
    "alanine aminotransferase (alt)": "alt",
    "alp": "alkaline phosphatase",
    "alkaline phosphatase (alp)": "alkaline phosphatase",
    "protein total": "total protein",
    "t3": "total t3",
    "t4": "total t4",
    "tsh (ultrasensitive)": "thyroid stimulating hormone",
    "tsh (thyroid stimulating hormone)": "thyroid stimulating hormone",
    "thyroid stimulating hormone (tsh)": "thyroid stimulating hormone",
    "vit d total": "vitamin d total",
    "vit b12": "vitamin b12",
    "cyanocobalamin (b12)": "vitamin b12",
    "cyanocobalamin (vitamin b12)": "vitamin b12",
    "glycated hb": "hba1c",
    "glycated hemoglobin (hba1c)": "hba1c",
    "fbs": "fasting glucose",
    "fasting blood sugar (fbs)": "fasting glucose",
    "glucose - fasting": "fasting glucose",
    "fasting glucose": "fasting glucose",
    "ppbs": "postprandial glucose",
    "postprandial blood sugar (ppbs)": "postprandial glucose",
}

# These names only collapse within the report where their context is known.
REPORT_NAME_ALIASES = {
    "report_06": {
        "urine colour": "colour",
        "urine clarity": "clarity",
        "urine ph": "ph",
        "urine specific gravity": "specific gravity",
        "urine sugar": "sugar",
        "urine albumin": "albumin",
        "urine ketones": "ketones",
        "urine leucocytes": "leucocytes",
        "urine erythrocytes": "erythrocytes",
        "urine squamous epithelial cells": "squamous epithelial cells",
        "c-reactive protein (crp)": "crp",
        "erythrocyte sedimentation rate (esr)": "e.s.r. (westergren)",
    },
    "report_11": {
        "urine color": "color",
        "urine appearance": "appearance",
        "urine reaction (ph)": "reaction (ph)",
        "urine specific gravity": "sp. gravity",
        "urine ketone bodies": "ketone bodies",
        "urine pus cells (wbc)": "pus cells (wbc)",
        "urine rbc": "rbc",
        "urine epithelial cells": "epithelial cells",
    },
}


EXPLICITLY_DISTINCT_NAME_PAIRS = {
    frozenset(("ldl cholesterol (direct)", "ldl cholesterol")),
}


def canonical_name(value, report_id=None):
    name = name_key(value)
    report_aliases = REPORT_NAME_ALIASES.get(report_id, {})
    if name in report_aliases:
        return name_key(report_aliases[name])
    return NAME_ALIASES.get(name, name)


def unit_key(value):
    return " ".join(str(value or "").casefold().split())


def value_key(value):
    if value is None or isinstance(value, bool):
        return str(value).casefold()
    text = str(value).strip().replace(" ", "")
    if "," in text:
        if not COMMA_NUMBER.fullmatch(text):
            return text.casefold()
        text = text.replace(",", "")
    try:
        number = Decimal(text)
        return number.normalize() if number.is_finite() else text.casefold()
    except InvalidOperation:
        return text.casefold()


def compare(gold_rows, extracted_rows, report_id=None):
    issues = {
        "missing_tests": [], "extra_tests": [], "wrong_values": [],
        "wrong_units": [], "wrong_names": [],
    }
    gold_names = defaultdict(list)
    extracted_names = defaultdict(list)
    for i, row in enumerate(gold_rows):
        gold_names[canonical_name(row.get("test_name"), report_id)].append(i)
    for i, row in enumerate(extracted_rows):
        extracted_names[canonical_name(row.get("test_name"), report_id)].append(i)

    pairs = []
    unmatched_gold, unmatched_extracted = set(), set(range(len(extracted_rows)))
    for name, gold_indices in gold_names.items():
        remaining_gold = list(gold_indices)
        remaining_extracted = list(extracted_names.get(name, []))
        while remaining_gold and remaining_extracted:
            gi, ei = remaining_gold.pop(0), remaining_extracted.pop(0)
            pairs.append((gi, ei))
            unmatched_extracted.remove(ei)
        unmatched_gold.update(remaining_gold)

    # Same value and unit uniquely identifies likely rows with a changed name.
    signatures_gold = defaultdict(list)
    signatures_extracted = defaultdict(list)
    for gi in unmatched_gold:
        row = gold_rows[gi]
        signatures_gold[(value_key(row.get("value")), unit_key(row.get("unit")))].append(gi)
    for ei in unmatched_extracted:
        row = extracted_rows[ei]
        signatures_extracted[(value_key(row.get("value")), unit_key(row.get("unit")))].append(ei)
    for signature, gis in signatures_gold.items():
        eis = signatures_extracted.get(signature, [])
        if len(gis) == len(eis) == 1:
            gi, ei = gis[0], eis[0]
            distinct_names = frozenset((
                canonical_name(gold_rows[gi].get("test_name"), report_id),
                canonical_name(extracted_rows[ei].get("test_name"), report_id),
            ))
            if distinct_names in EXPLICITLY_DISTINCT_NAME_PAIRS:
                continue
            pairs.append((gi, ei))
            unmatched_gold.remove(gi)
            unmatched_extracted.remove(ei)
            issues["wrong_names"].append({"gold": gold_rows[gi].get("test_name"),
                                          "extracted": extracted_rows[ei].get("test_name")})

    issues["missing_tests"] = [gold_rows[i] for i in sorted(unmatched_gold)]
    issues["extra_tests"] = [extracted_rows[i] for i in sorted(unmatched_extracted)]
    for gi, ei in pairs:
        gold, extracted = gold_rows[gi], extracted_rows[ei]
        if value_key(gold.get("value")) != value_key(extracted.get("value")):
            issues["wrong_values"].append({"test": gold.get("test_name"),
                                            "gold": gold.get("value"),
                                            "extracted": extracted.get("value")})
        if unit_key(gold.get("unit")) != unit_key(extracted.get("unit")):
            issues["wrong_units"].append({"test": gold.get("test_name"),
                                          "gold": gold.get("unit"),
                                          "extracted": extracted.get("unit")})
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir", type=Path,
                        help="Directory containing saved report_XX.json extraction results")
    args = parser.parse_args()
    results_dir = args.results_dir.resolve()
    if not results_dir.is_dir():
        parser.error(f"Results directory does not exist: {results_dir}")

    total = defaultdict(int)
    for gold_path in sorted(GOLD_DIR.glob("report_*.json")):
        result_path = results_dir / gold_path.name
        print(f"\n{gold_path.stem}")
        if not result_path.is_file():
            print(f"  missing extraction file: {result_path}")
            total["missing_extraction_files"] += 1
            continue
        try:
            gold = json.loads(gold_path.read_text(encoding="utf-8"))["tests"]
            extracted = json.loads(result_path.read_text(encoding="utf-8"))["tests"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            print(f"  could not read tests: {error}")
            total["invalid_files"] += 1
            continue
        issues = compare(gold, extracted, gold_path.stem)
        for category, rows in issues.items():
            total[category] += len(rows)
            print(f"  {category}: {len(rows)}")
            for row in rows:
                print(f"    {json.dumps(row, ensure_ascii=False)}")

    print("\nTotals")
    for category, count in total.items():
        print(f"  {category}: {count}")


if __name__ == "__main__":
    main()

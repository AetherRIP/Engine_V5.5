"""Build and validate the candidate criterion-level ground truth.

The marks are derived from the printed mark scheme (``scheme_p01..p21``) and
each award was re-checked against the student's handwritten working.  This is a
*candidate* reference: no teacher has certified it, so every report must label
accuracy as provisional.

Two items are deliberately excluded from scoring because the source documents
disagree with each other:

* Q12 — the student page prints the Q11 expression again, while the scheme's
  Q12 is a different question (``4p + 20 + 7p - 14``).  No honest mark exists.
* Q16(d) — the scheme marks a part that is not printed on the student page.

Both stay in the dataset (a strategy still sees them) and are recorded as
``excluded_source_mismatch`` / ``excluded_not_printed``; they are not silently
turned into zero-mark questions.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config

# fmt: off
# id, prompt, page, scheme_page, scheme_ref, max_marks, criteria, awarded, evidence, confidence, status
ITEMS = [
    ("1a", "Expand and simplify 6(4 - 3y)", 1, 2, "June 15/4H/Q7 a", 1,
     [("B1", "24 - 18y")], [True], "Working shows 12x - 18y? Final 24 - 18y is correct.", "high", "scored"),
    ("1d", "Expand and simplify (y + 10)(y - 2)", 1, 2, "June 15/4H/Q7 d", 2,
     [("M1", "3 of 4 correct terms or 4 ignoring signs"), ("A1", "y^2 + 8y - 20")], [True, True],
     "y^2 + 10y - 2y - 20 then y^2 + 8y - 20.", "high", "scored"),
    ("2", "Expand and simplify 5(2p - 3)", 1, 2, "June 15/4HR/Q9 a", 1,
     [("B1", "10p - 15")], [True], "Final 10p - 15.", "high", "scored"),
    ("3", "Expand and simplify (x + 5)(x - 1)", 1, 2, "Jan 16/3H/Q4 c", 2,
     [("M1", "3 correct terms out of 4"), ("A1", "x^2 + 4x - 5")], [True, True],
     "x^2 + 5x - x - 5 then x^2 + 4x - 5.", "high", "scored"),
    ("4", "Expand and simplify (t - 4)(t + 5)", 1, 2, "Jan 16/3HR/Q2 b", 2,
     [("M1", "3 correct terms out of 4"), ("A1", "t^2 + t - 20")], [True, True],
     "t^2 - 4t + 5t - 20 then t^2 + t - 20.", "high", "scored"),
    ("5", "Expand and simplify x(x + 2)", 1, 2, "Jan 16/4H/Q9 a", 1,
     [("B1", "x^2 + 2x")], [True], "x^2 + 2x.", "high", "scored"),
    ("6", "Expand and simplify (2x + 3)^2 - (2x - 3)^2", 1, 3, "Jan 16/4HR/Q12", 3,
     [("M1", "any one correct expansion"), ("M1", "fully correct expansions, correct removal of bracket"),
      ("A1", "24x")], [True, True, True],
     "Both expansions correct, bracket signs handled, final 24x.", "high", "scored"),
    ("7", "Expand and simplify (x + 2)(x - 9)", 1, 3, "June 16/3H/Q7 b", 2,
     [("M1", "3 of 4 terms or 4 ignoring signs"), ("A1", "x^2 - 7x - 18")], [True, True],
     "x^2 - 9x + 2x - 18 then x^2 - 7x - 18.", "high", "scored"),
    ("8", "Expand and simplify (2y - 3)(4y + 1)", 1, 3, "June 16/3HR/Q12 c", 2,
     [("M1", "3 of 4 terms or 4 ignoring signs"), ("A1", "8y^2 + 10y - 3")], [True, True],
     "8y^2 + 2y - 12y - 3 then 8y^2 + 10y - 3.", "high", "scored"),
    ("9", "Expand and simplify 4(2x + 3) + 2(x + 5)", 2, 4, "June 16/4H/Q5 d", 2,
     [("M1", "any 3 terms correct out of 4"), ("A1", "10x + 22")], [True, True],
     "8x + 12 + 2x + 10 then 10x + 22.", "high", "scored"),
    ("10", "Expand and simplify 2(3y + 3) + 2(y - 4)", 2, 4, "June 16/4HR/Q2 b", 2,
     [("M1", "3 correct terms"), ("A1", "8y - 2")], [True, True],
     "6y + 6 + 2y - 8 then 8y - 2.", "high", "scored"),
    ("11", "Expand and simplify 4x(x + 3) - (2x - 3)^2", 2, 4, "June 16/4HR/Q14 c", 3,
     [("M1", "expansion of 4x(x + 3) or (2x - 3)^2"), ("M1", "fully correct expansions, correct removal of bracket"),
      ("A1", "24x - 9")], [True, True, True],
     "4x^2 + 12x - (4x^2 - 12x + 9) then 24x - 9.", "high", "scored"),
    ("12", "Duplicate of Q11 on the student page", 2, 4, "Jan 17/3H/Q5 b", 2, [], [], 
     "The printed question is the Q11 expression; the scheme's Q12 is 4p + 20 + 7p - 14. "
     "Question paper and mark scheme disagree, so no mark can be awarded honestly.",
     "n/a", "excluded_source_mismatch"),
    ("13", "Expand and simplify (2x + 3)^2 - (2x + 3)(x - 5)", 3, 5, "Jan 17/3H/Q9", 3,
     [("M1", "at least 3 terms correct in first expansion"), ("M1", "at least 3 terms correct in second expansion"),
      ("A1", "2x^2 + 19x + 24")], [True, True, True],
     "4x^2 + 12x + 9 - (2x^2 - 7x - 15) then 2x^2 + 19x + 24.", "high", "scored"),
    ("14", "Expand and simplify (k + 9)(k - 5)", 3, 5, "Jan 17/3HR/Q11 b", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "k^2 + 4k - 45")], [True, True],
     "k^2 - 5k + 9k - 45 then k^2 + 4k - 45 (first line's -9k reading is ambiguous, final is correct).",
     "medium", "scored"),
    ("15", "Expand and simplify 3(4p + 5)", 3, 5, "Jan 17/4HR/Q7 a", 1,
     [("B1", "12p + 15")], [True], "12p + 15.", "high", "scored"),
    ("16b", "Expand p(2p - 3)", 3, 6, "Jan 18/4H/Q10 b", 1,
     [("B1", "2p^2 - 3p")], [True], "2p^2 - 3p.", "high", "scored"),
    ("16d", "Expand and simplify (x + 3)(x - 7)", 3, 6, "Jan 18/4H/Q10 d", 2, [], [],
     "Part (d) is marked in the scheme but is not printed on the student page.",
     "n/a", "excluded_not_printed"),
    ("17", "Expand and simplify (x + 3)(x - 6)", 3, 6, "Jan 18/4HR/Q7 c", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "x^2 - 3x - 18")], [True, True],
     "x^2 - 6x + 3x - 18 then x^2 - 3x - 18.", "high", "scored"),
    ("18", "Expand and simplify (2x - 1)(x + 3)(x - 5)", 3, 7, "June 18/1H/Q11 a", 3,
     [("M1", "expansion of any 2 of 3 brackets"), ("M1", "dependent second expansion"),
      ("A1", "2x^3 - 5x^2 - 28x + 15")], [True, True, True],
     "(2x - 1)(x^2 - 2x - 15) then 2x^3 - 5x^2 - 28x + 15.", "high", "scored"),
    ("19", "Expand and simplify (3x - 4y)(x + 3y)", 3, 7, "June 18/1HR/Q14 b", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "3x^2 + 5xy - 12y^2")], [True, True],
     "3x^2 + 9xy - 4xy - 12y^2 then 3x^2 + 5xy - 12y^2.", "high", "scored"),
    ("20", "Expand and simplify (e + 3)(e - 5)", 4, 8, "Jan 19/1H/Q1 b", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "e^2 - 2e - 15")], [True, True],
     "e^2 - 5e + 3e - 15 then e^2 - 2e - 15.", "high", "scored"),
    ("21", "Expand and simplify 4n(n - 3)(n + 5)", 4, 8, "Jan 19/1HR/Q15 b", 2,
     [("M1", "correct partial expansion"), ("A1", "4n^3 + 8n^2 - 60n")], [True, True],
     "4n(n^2 + 2n - 15) then 4n^3 + 8n^2 - 60n.", "high", "scored"),
    ("22", "Expand and simplify (x + 9)(x - 2)", 4, 8, "June 19/1H/Q3 c", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "x^2 + 7x - 18")], [True, True],
     "x^2 - 2x + 9x - 18 then x^2 + 7x - 18.", "high", "scored"),
    ("23", "Expand and simplify (x + 2)(2x + 3)(x - 7)", 4, 9, "June 19/1HR/Q18 a", 3,
     [("M1", "one pair of brackets expanded, 3 of 4 terms"), ("M1dep", "second expansion, 3 of 6 or 4 of 8 terms"),
      ("A1", "2x^3 - 7x^2 - 43x - 42")], [True, True, True],
     "(x + 2)(2x^2 - 11x - 21) then 2x^3 - 7x^2 - 43x - 42.", "high", "scored"),
    ("24", "Expand and simplify (m - 8)(m + 5)", 4, 9, "Jan 20/1H/Q7 a", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "m^2 - 3m - 40")], [True, True],
     "m^2 + 5m - 8m - 40 then m^2 - 3m - 40.", "high", "scored"),
    ("25", "Expand and simplify (x + 2)(x - 5)", 4, 10, "Jan 20/1HR/Q3 c", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "x^2 - 3x - 10")], [True, True],
     "x^2 - 5x + 2x - 10 then x^2 - 3x - 10.", "high", "scored"),
    ("26", "Expand and simplify (4x + 1)(x - 3)(5x + 6)", 5, 10, "June 20/1HR/Q14", 3,
     [("M1", "two brackets multiplied, 3 of 4 terms"), ("M1", "dependent third-factor expansion"),
      ("A1", "20x^3 - 31x^2 - 81x - 18")], [True, True, False],
     "Working reaches 20x^3 - 31x^2 + 63x - 18: first two stages are right, the x term is not.",
     "high", "scored"),
    ("27", "Expand and simplify 2x(x - 5)(x - 3)", 5, 11, "Jan 21/1H/Q12 b", 3,
     [("M1", "2x multiplied by a bracket or 3 of 4 terms"), ("M1", "dependent third-factor expansion"),
      ("A1", "2x^3 - 16x^2 + 30x")], [True, True, True],
     "2x(x^2 - 8x + 15) then 2x^3 - 16x^2 + 30x.", "high", "scored"),
    ("28", "Expand and simplify (x + 4)(x - 2)(x + 1)", 5, 12, "Jan 21/1HR/Q16 a", 3,
     [("M1", "two brackets correctly expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "x^3 + 3x^2 - 6x - 8")], [True, True, True],
     "(x + 4)(x^2 - x - 2) then x^3 + 3x^2 - 6x - 8.", "high", "scored"),
    ("29", "Expand and simplify 4x(2x + 5) - 3x(2x - 3)", 5, 13, "Jan 21/2H/Q5 a", 2,
     [("M1", "3 correct terms or 4 ignoring signs"), ("A1", "2x^2 + 29x")], [True, True],
     "8x^2 + 20x - 6x^2 + 9x then 2x^2 + 29x.", "high", "scored"),
    ("30", "Expand and simplify 4x(3x + 1)(2x - 3)", 5, 14, "June 21/1H/Q13", 3,
     [("M1", "two of three factors expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "24x^3 - 28x^2 - 12x")], [True, True, False],
     "22x^3 - 28x^2 - 12x: first two stages right, leading coefficient wrong.", "high", "scored"),
    ("31", "Expand and simplify 4x(x - 5)(2x + 3)", 5, 15, "Nov 21/2H/Q12 c", 3,
     [("M1", "one factor pair expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "8x^3 - 28x^2 - 60x")], [True, True, False],
     "8x^3 - 6x^2 - 60x: expansions right, final simplification of the x^2 term wrong.",
     "high", "scored"),
    ("32", "Expand and simplify 5x(x + 2)(3x - 4)", 6, 16, "Jan 22/1H/Q13 a", 3,
     [("M1", "two of three factors expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "15x^3 + 10x^2 - 40x")], [True, True, True],
     "15x^3 - 20x^2 + 30x^2 - 40x then 15x^3 + 10x^2 - 40x.", "high", "scored"),
    ("33", "Expand and simplify n(n - 4)(3n + 5)", 6, 17, "Jan 22/1HR/Q12 a", 2,
     [("M1", "correct partial expansion"), ("A1", "3n^3 - 7n^2 - 20n")], [True, True],
     "3n^3 + 5n^2 - 12n^2 - 20n then 3n^3 - 7n^2 - 20n.", "high", "scored"),
    ("34", "Expand and simplify 3x(2x - 5)^2", 6, 18, "Jan 23/1H/Q13", 3,
     [("M1", "3x by (2x - 5) or (2x - 5)^2 expanded"), ("M1", "dependent expansion"),
      ("A1", "12x^3 - 60x^2 + 75x")], [True, True, True],
     "3x(4x^2 - 20x + 25) then 12x^3 - 60x^2 + 75x.", "high", "scored"),
    ("35", "Expand and simplify 5x(3x + 4)(2x - 1)", 6, 19, "Jan 23/2HR/Q12 c", 3,
     [("M1", "two of three factors expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "30x^3 + 25x^2 - 20x")], [True, True, True],
     "30x^3 - 15x^2 + 40x^2 - 20x then 30x^3 + 25x^2 - 20x.", "high", "scored"),
    ("36", "Expand and simplify (x + 6)(3x - 2)(x + 6)", 6, 20, "June 23/2H/Q17 a", 3,
     [("M1", "two brackets correctly expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "3x^3 + 34x^2 + 84x - 72")], [True, True, False],
     "3x^3 + 34x^2 + 86x - 72: expansions right, one addition slip in the x term.",
     "high", "scored"),
    ("37a", "Expand and simplify (3x + 1)(2 - x)(4 + x)", 7, 21, "June 24/1HR/Q14 (a)", 3,
     [("M1", "two brackets correctly expanded"), ("M1", "dependent third-factor expansion"),
      ("A1", "-3x^3 - 7x^2 + 22x + 8")], [True, True, True],
     "(3x + 1)(8 - 2x - x^2) then -3x^3 - 7x^2 + 22x + 8.", "high", "scored"),
    ("37b", "Simplify fully (a^9 b^5 / (a^3 b))^(1/2)", 7, 21, "June 24/1HR/Q14 (b)", 3,
     [("M1", "simplify a and b in the fraction"), ("M1", "apply the power to both terms"),
      ("A1", "a^3 b^2")], [False, False, False],
     "The part is printed but the answer space is blank (only crossed-out marks).", "high", "scored"),
]
# fmt: on


def build() -> dict:
    items = []
    for (item_id, prompt, page, scheme_page, scheme_ref, max_marks, criteria,
         awarded, evidence, confidence, status) in ITEMS:
        if status == "scored" and len(criteria) != len(awarded):
            raise ValueError(f"{item_id}: criteria/awards length mismatch")
        if status == "scored" and not any(awarded) and max_marks > 0:
            pass  # a legitimate zero (Q37b)
        items.append({
            "id": item_id,
            "prompt": prompt,
            "student_page": page,
            "scheme_page": scheme_page,
            "scheme_ref": scheme_ref,
            "max_marks": max_marks,
            "criteria": [
                {"id": f"{code}{index + 1}", "code": code, "text": text, "awarded": bool(awarded[index]) if status == "scored" else None}
                for index, (code, text) in enumerate(criteria)
            ],
            "expected_mark": sum(1 for value in awarded if value) if status == "scored" else None,
            "status": status,
            "confidence": confidence,
            "evidence": evidence,
        })

    scored = [item for item in items if item["status"] == "scored"]
    total = sum(item["max_marks"] for item in scored)
    expected = sum(item["expected_mark"] for item in scored)
    return {
        "paper_id": config.PAPER_ID,
        "title": "Algebraic Manipulation workbook, pages 340-346",
        "reference_source": "printed criterion-level mark scheme retained by V5",
        "verification": {
            "status": "candidate_not_teacher_certified",
            "verified_by": None,
            "verified_on": None,
            "warning": (
                "Marks were derived by the benchmark author from the printed scheme and an "
                "independent re-solve. No qualified teacher has certified them. Accuracy "
                "measured against this reference is provisional, never certified."
            ),
        },
        "totals": {
            "items_total": len(items),
            "items_scored": len(scored),
            "items_excluded": len(items) - len(scored),
            "marks_available_scored": total,
            "candidate_marks_awarded": expected,
            "candidate_percentage": round(100 * expected / total, 2) if total else None,
            "printed_marks_all_items": 87,
            "excluded_marks": sum(item["max_marks"] for item in items if item["status"] != "scored"),
        },
        "exclusions": [
            {"id": item["id"], "status": item["status"], "evidence": item["evidence"]}
            for item in items if item["status"] != "scored"
        ],
        "items": items,
    }


def write() -> dict:
    config.ensure_dirs()
    data = build()
    path = config.GROUND_TRUTH_DIR / "paper-01.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


def load() -> dict:
    path = config.GROUND_TRUTH_DIR / "paper-01.json"
    if not path.is_file():
        return write()
    return json.loads(path.read_text(encoding="utf-8"))


def validate(data: dict | None = None) -> list[str]:
    """Return a list of integrity problems (empty when the reference is sound)."""
    data = data or load()
    problems: list[str] = []
    ids = [item["id"] for item in data.get("items", [])]
    if len(ids) != len(set(ids)):
        problems.append("duplicate item ids")
    for item in data.get("items", []):
        if item["status"] != "scored":
            if item.get("criteria"):
                problems.append(f"{item['id']}: excluded item still has criteria")
            continue
        expected = sum(1 for criterion in item["criteria"] if criterion["awarded"])
        if expected != item["expected_mark"]:
            problems.append(f"{item['id']}: expected_mark disagrees with criteria")
        if item["expected_mark"] > item["max_marks"]:
            problems.append(f"{item['id']}: award exceeds max_marks")
        if len(item["criteria"]) != item["max_marks"]:
            problems.append(f"{item['id']}: criteria count differs from max_marks")
    scored = [item for item in data.get("items", []) if item["status"] == "scored"]
    totals = data.get("totals", {})
    if totals.get("marks_available_scored") != sum(item["max_marks"] for item in scored):
        problems.append("marks_available_scored total is inconsistent")
    if totals.get("candidate_marks_awarded") != sum(item["expected_mark"] for item in scored):
        problems.append("candidate_marks_awarded total is inconsistent")
    return problems


def review_sheet(data: dict | None = None) -> str:
    data = data or load()
    lines = [
        "# Candidate marking review sheet — paper-01",
        "",
        "**Status: NOT TEACHER-CERTIFIED.** These marks come from the printed scheme and an",
        "independent re-solve. A qualified teacher must confirm every line before the accuracy",
        "figures can be called certified.",
        "",
        f"- Scoreable items: {data['totals']['items_scored']} "
        f"({data['totals']['marks_available_scored']} marks)",
        f"- Excluded items: {data['totals']['items_excluded']} "
        f"({data['totals']['excluded_marks']} marks)",
        f"- Candidate total: {data['totals']['candidate_marks_awarded']} / "
        f"{data['totals']['marks_available_scored']}",
        "",
        "| Item | Marks | Candidate | Scheme reference | Evidence / uncertainty |",
        "|---|---|---|---|---|",
    ]
    for item in data["items"]:
        if item["status"] != "scored":
            lines.append(f"| {item['id']} | {item['max_marks']} | EXCLUDED | {item['scheme_ref']} | "
                         f"{item['status']}: {item['evidence']} |")
            continue
        criteria = "; ".join(
            f"{criterion['code']}{'+' if criterion['awarded'] else '-'}" for criterion in item["criteria"]
        )
        lines.append(f"| {item['id']} | {item['max_marks']} | {item['expected_mark']} | "
                     f"{item['scheme_ref']} | {criteria}. {item['evidence']} |")
    lines.extend([
        "",
        "## Reviewer record",
        "",
        "Name: ______________________  Date: __________",
        "",
        "Signature: ______________________",
        "",
        "By signing, the reviewer confirms each mark above against the printed scheme and the",
        "student's working, or records a dispute. Until then the benchmark reports",
        "**provisional** accuracy only.",
        "",
    ])
    return "\n".join(lines)


if __name__ == "__main__":
    data = write()
    problems = validate(data)
    (config.GROUND_TRUTH_DIR / "REVIEW_SHEET.md").write_text(review_sheet(data), encoding="utf-8")
    print(json.dumps({"totals": data["totals"], "problems": problems}, indent=2))

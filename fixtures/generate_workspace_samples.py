"""Sample documents for the Engineering and Finance workspaces.

Everything is invented. Run inside the worker container:

    docker compose run --rm --no-deps -v "D:/sih/psu/fixtures:/app/fixtures" \
        -v "D:/sih/psu/frontend/public/samples:/app/samples" worker \
        python fixtures/generate_workspace_samples.py
"""
from pathlib import Path

import pymupdf

OUT = Path("/app/samples")
OUT.mkdir(parents=True, exist_ok=True)
STAMP = "SYNTHETIC DEMO DATA - NOT A REAL COMPANY DOCUMENT"

ENGINEERING = f"""{STAMP}

ENGINEERING STANDARD ENG-STD-07
Code Review and Testing Standard  |  Revision 2  |  Effective 1 March 2026

1. PURPOSE

1.1 This standard sets the minimum testing and review requirements for
software used in plant utilities, calculators and reporting tools.

2. TESTING

2.1 Every function must have at least one automated test.

2.2 A value that equals a limit must be tested explicitly. A reading exactly
at the limit is within the limit, and the test suite must confirm this.

2.3 A change may not be released while any automated test is failing.

3. REVIEW

3.1 Changes to safety-related calculations need a second reviewer.

3.2 Plant utilities must not make network calls. All data stays on site.

4. RECORDS

4.1 The test run output is kept with the change record.
"""

PROCUREMENT = f"""{STAMP}

PROCUREMENT POLICY PROC-POL-03
Purchase Approval and Vendor Selection  |  Revision 4  |  Effective 1 April 2026

1. PURPOSE

1.1 This policy sets who may approve a purchase and how vendors are chosen.

2. APPROVAL LIMITS

2.1 A purchase up to 200000 INR is approved by the department head.

2.2 A purchase above 200000 INR and up to 500000 INR needs the procurement
manager's approval.

2.3 A purchase above 500000 INR needs committee approval and at least three
written quotes.

3. VENDOR SELECTION

3.1 A vendor rated below 3.5 may not be selected without a written
justification.

3.2 Delivery longer than 30 days for a critical spare needs a written
justification.

4. AUTHORISATION

4.1 No automated tool may record an approval on the approver's behalf. The
approver signs personally.
"""

QUOTES = [
    ("Q-01", "Apex Valves", "Gate valve 6in", 42000, 10, 21, 4.4),
    ("Q-02", "Bharat Flow Systems", "Gate valve 6in", 39500, 10, 35, 3.9),
    ("Q-03", "Meridian Pumps", "Centrifugal pump", 185000, 3, 28, 4.6),
    ("Q-04", "Sterling Seals", "Mechanical seal kit", 12500, 20, 14, 3.2),
    ("Q-05", "Kavach Safety", "Gas detector", 27000, 12, 18, 4.1),
    ("Q-06", "Orion Hydraulics", "Centrifugal pump", 172000, 3, 45, 3.4),
    ("Q-07", "Apex Valves", "Control valve", 98000, 6, 30, 4.4),
    ("Q-08", "Bharat Flow Systems", "Flange set", 8200, 40, 12, 3.9),
    ("Q-09", "Kavach Safety", "Fire suppression panel", 145000, 2, 26, 4.1),
    ("Q-10", "Sterling Seals", "Gasket pack", 3100, 60, 9, 3.2),
]


def pdf(name, text, split_at):
    head, tail = text.split(split_at, 1)
    pages = [head.rstrip(), f"{STAMP}\n\n(continued)\n\n{split_at}{tail}"]
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page(width=595, height=842)
        page.insert_textbox(pymupdf.Rect(56, 56, 539, 786), body,
                            fontname="cour", fontsize=10.5)
    doc.save(str(OUT / name))
    print(f"  {name}: {doc.page_count} pages")
    doc.close()


def quotes_xlsx():
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Quotes"
    ws.append(["quote_id", "vendor", "item", "unit_price_inr", "quantity",
               "total_cost_inr", "delivery_days", "vendor_rating"])
    for q_id, vendor, item, unit, qty, days, rating in QUOTES:
        ws.append([q_id, vendor, item, unit, qty, unit * qty, days, rating])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    wb.save(OUT / "vendor_quotes.xlsx")
    over = [q[0] for q in QUOTES if q[3] * q[4] > 500000]
    print(f"  vendor_quotes.xlsx: {len(QUOTES)} quotes, above 500000: {over}")


pdf("engineering_standards.pdf", ENGINEERING, "3. REVIEW")
pdf("procurement_policy.pdf", PROCUREMENT, "3. VENDOR SELECTION")
quotes_xlsx()

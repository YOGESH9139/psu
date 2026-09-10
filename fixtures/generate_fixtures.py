"""Build the synthetic demo fixture pack.

Everything here is invented. No real plant, document or measurement is used, and
every page is stamped SYNTHETIC FIXTURE.

Run it inside the worker container, which already has PyMuPDF, Pillow and
openpyxl installed:

    docker compose run --rm --entrypoint python worker fixtures/generate_fixtures.py

Outputs (into fixtures/):
    inspection_report.pdf   3-page *scanned-looking* corrosion report, with an
                            equipment photograph and a handwritten annotation
    corrosion_sop.pdf       SOP with the 2.0 mm escalation threshold
    pid_drawing.png         simple schematic for visual identification only
    readings_log.xlsx       3 sheets; thickness readings, some below threshold
    coding_fixture.py       function with an off-by-one bug + failing tests
    golden_findings.json    the test oracle
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFilter

FIXTURES = Path(__file__).resolve().parent
RENDER_DPI = 150
SEED = 20260910

random.seed(SEED)

STAMP = "SYNTHETIC FIXTURE — NOT A REAL INSPECTION RECORD"

# ─── Source content ─────────────────────────────────────────────────────────

REPORT_PAGES = [
    f"""{STAMP}

ULTRASONIC THICKNESS INSPECTION REPORT
Report No.  MRPL-SYN-2026-0441
Facility    Synthetic Refinery Unit 3 (training data)
Asset       Crude overhead line 12-P-204, elbow E-07
Date        2026-08-14
Inspector   A. Rao, Level II UT (synthetic persona)

1. SCOPE

Routine ultrasonic thickness survey of elbow E-07 on the crude overhead
line, following the 5000-hour interval defined in the site inspection
schedule. Nominal wall thickness for this component is 9.5 mm.

2. METHOD

Contact ultrasonic thickness measurement at twelve grid points, using a
5 MHz dual element probe. Surface prepared by wire brushing. Couplant
applied at each point. Calibration verified against a step wedge before
and after the survey.

3. GENERAL CONDITION

External coating breakdown observed on the outer radius of the elbow over
an area of roughly 180 by 120 mm. Product-side scale visible through the
breakdown. No through-wall penetration and no active leak was observed at
the time of the survey.
""",
    f"""{STAMP}

4. MEASURED RESULTS

Grid point   Measured (mm)   Loss from nominal (mm)
G-01              9.4              0.1
G-02              9.1              0.4
G-03              8.8              0.7
G-04              7.9              1.6
G-05              7.1              2.4
G-06              6.8              2.7
G-07              7.4              2.1
G-08              8.2              1.3
G-09              9.0              0.5
G-10              9.3              0.2
G-11              9.4              0.1
G-12              9.2              0.3

Minimum measured thickness      6.8 mm at grid point G-06
Maximum wall loss               2.7 mm at grid point G-06
Nominal wall thickness          9.5 mm

5. OBSERVATIONS

The deepest wall loss is concentrated on the outer radius of the elbow,
coincident with the coating breakdown described in section 3. The loss
pattern is consistent with localised external corrosion under disbonded
coating rather than internal erosion.
""",
    f"""{STAMP}

6. PHOTOGRAPH

See attached photograph of the affected outer radius, showing coating
breakdown and surface product deposits at grid points G-05 through G-07.

7. INSPECTOR NOTE

The measured maximum wall loss of 2.7 mm exceeds the site escalation
threshold. This report is referred to the integrity engineer for a
fitness-for-service assessment before the unit returns to full rate.

8. NEXT SURVEY

Recommended re-inspection interval reduced to 1000 hours pending the
outcome of the fitness-for-service assessment.
""",
]

SOP_TEXT = f"""{STAMP}

SOP-CORR-014
CORROSION FINDING ASSESSMENT AND ESCALATION
Revision 4 · Effective 2026-01-01 · Synthetic training document

1. PURPOSE

1.1 This procedure defines how measured wall loss found during a thickness
survey is classified, and when a finding must be escalated to an
authorized integrity engineer.

2. SCOPE

2.1 Applies to all pressure-containing piping and vessel components
covered by the site thickness survey programme.

3. CLASSIFICATION OF WALL LOSS

3.1 Wall loss is calculated as nominal wall thickness minus the minimum
measured thickness at any grid point on the component.

3.2 Wall loss of 1.0 mm or less is recorded as ROUTINE. The component
remains on its existing survey interval.

3.3 Wall loss greater than 1.0 mm and up to and including 2.0 mm is
recorded as MONITOR. The survey interval for that component is halved.

3.4 Wall loss exceeding 2.0 mm is recorded as ESCALATE. Escalation is
mandatory and may not be waived by the inspecting technician.

4. ESCALATION PROCESS

4.1 An ESCALATE finding is referred to an authorized integrity engineer
within one working day of the survey.

4.2 The integrity engineer performs a fitness-for-service assessment
before the affected component is returned to full operating rate.

4.3 A written approval note recording the assessment, the applicable
clauses of this procedure and the engineer's decision is filed against
the asset record. The note is not valid until signed by the engineer.

4.4 No automated system, decision-support tool or reporting workflow may
record the engineer's approval on their behalf. The signature must be
applied by the authorized person.

5. COATING BREAKDOWN

5.1 Where external coating breakdown is observed alongside measured wall
loss, the finding is treated as external corrosion under disbonded
coating and the coating condition is recorded with the thickness result.

6. RECORDS

6.1 Survey results, photographs and the signed approval note are retained
against the asset record for the life of the asset.
"""

CODING_FIXTURE = '''"""Coding fixture: contains a deliberate off-by-one bug.

`grid_points_below_limit` should return every reading strictly below the
limit, but the comparison includes equality, so a reading exactly at the
limit is wrongly reported as a breach. The tests below fail until it is fixed.
"""


def grid_points_below_limit(readings: dict[str, float], limit: float) -> list[str]:
    """Return the grid points whose measured thickness is below `limit`."""
    breaches = []
    for point, thickness in readings.items():
        if thickness <= limit:  # BUG: should be `<`
            breaches.append(point)
    return breaches


READINGS = {"G-01": 9.4, "G-05": 7.1, "G-06": 6.8, "G-09": 8.0}


def test_strictly_below_limit():
    assert grid_points_below_limit(READINGS, 8.0) == ["G-05", "G-06"]


def test_reading_exactly_at_limit_is_not_a_breach():
    assert "G-09" not in grid_points_below_limit(READINGS, 8.0)


def test_no_breaches_when_limit_is_low():
    assert grid_points_below_limit(READINGS, 6.0) == []
'''

GOLDEN_FINDINGS = {
    "_note": "Test oracle for the synthetic fixture pack. All values are invented.",
    "inspection_report.pdf": {
        "expected_ocr_terms": [
            "ULTRASONIC", "THICKNESS", "elbow", "9.5", "6.8", "2.7", "G-06",
            "coating", "escalation",
        ],
        "min_ocr_words_per_page": 20,
        "nominal_wall_thickness_mm": 9.5,
        "minimum_measured_thickness_mm": 6.8,
        "maximum_wall_loss_mm": 2.7,
        "worst_grid_point": "G-06",
        "expected_classification": "ESCALATE",
    },
    "corrosion_sop.pdf": {
        "escalation_threshold_mm": 2.0,
        "expected_citation_clauses": ["3.4", "4.1", "4.2", "4.4"],
        "expected_citation_count_min": 2,
        "clause_text_fragments": [
            "Wall loss exceeding 2.0 mm",
            "authorized integrity engineer",
            "may not be waived",
        ],
    },
    "readings_log.xlsx": {
        "sheets": ["Thickness Survey", "Coating Condition", "Survey Schedule"],
        "threshold_column": "wall_loss_mm",
        "threshold_value": 2.0,
        "expected_rows_above_threshold": 3,
        "expected_grid_points_above_threshold": ["G-05", "G-06", "G-07"],
    },
    "coding_fixture.py": {
        "bug": "off-by-one: `<=` should be `<` in grid_points_below_limit",
        "expected_first_run": "fail",
        "expected_after_one_repair": "pass",
        "failing_test": "test_reading_exactly_at_limit_is_not_a_breach",
    },
    "approval_note.docx": {
        "required_headings": [
            "Purpose", "Source Report Metadata", "Extracted Findings",
            "Applicable SOP Clauses", "Recommended Action", "Risk Notice", "Approval",
        ],
        "min_citations": 2,
        "must_not_self_approve": True,
    },
}


# ─── PDF helpers ────────────────────────────────────────────────────────────

def _text_pdf(pages: list[str], font_size: float = 9.5) -> fitz.Document:
    """A clean, born-digital PDF with a real text layer."""
    doc = fitz.open()
    for body in pages:
        page = doc.new_page(width=595, height=842)  # A4
        page.insert_textbox(
            fitz.Rect(56, 56, 539, 786),
            body,
            fontname="cour",       # monospace keeps the results table aligned
            fontsize=font_size,
            align=fitz.TEXT_ALIGN_LEFT,
        )
    return doc


def _equipment_photograph(width: int = 460, height: int = 300) -> Image.Image:
    """A synthetic 'photograph' of a corroded elbow. Deliberately crude — it is
    a stand-in for a real photo, and is labelled as such."""
    img = Image.new("RGB", (width, height), (108, 112, 116))
    draw = ImageDraw.Draw(img)

    # Pipe body running across the frame, with an elbow bend.
    draw.rounded_rectangle([30, 110, 300, 200], radius=14, fill=(142, 146, 150))
    draw.rounded_rectangle([250, 60, 340, 250], radius=14, fill=(136, 140, 144))
    draw.arc([230, 90, 360, 220], start=270, end=90, fill=(90, 94, 98), width=6)

    # Coating breakdown patch with corrosion product.
    for _ in range(1400):
        x = random.randint(255, 335)
        y = random.randint(95, 215)
        shade = random.randint(0, 60)
        draw.point((x, y), fill=(120 + shade, 62 + shade // 2, 28 + shade // 3))

    # Pitting.
    for _ in range(45):
        x = random.randint(258, 332)
        y = random.randint(100, 210)
        r = random.randint(2, 6)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(72, 34, 14))

    # Scale bar and label.
    draw.rectangle([30, height - 34, 130, height - 26], fill=(240, 240, 240))
    draw.text((30, height - 22), "100 mm (approx)", fill=(240, 240, 240))
    draw.text((30, 20), "SYNTHETIC IMAGE - GENERATED, NOT A REAL PHOTOGRAPH",
              fill=(250, 230, 120))
    draw.text((250, 226), "G-05 .. G-07", fill=(250, 250, 250))

    return img.filter(ImageFilter.GaussianBlur(0.6))


def _handwriting(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str) -> None:
    """Wobbly, slanted text standing in for a handwritten margin note."""
    x, y = xy
    for char in text:
        dy = random.randint(-2, 2)
        draw.text((x, y + dy), char, fill=(30, 40, 160))
        x += random.randint(6, 9)


def _scanify(pixmap: fitz.Pixmap, page_index: int) -> Image.Image:
    """Make a rendered page look like it came off a flatbed: slight skew,
    paper tone, sensor noise and a soft focus. This is what forces the demo to
    exercise real OCR instead of reading a text layer."""
    img = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)

    # Warm paper tone.
    paper = Image.new("RGB", img.size, (250, 247, 238))
    img = Image.blend(img, paper, 0.10)

    draw = ImageDraw.Draw(img)

    if page_index == 2:
        photo = _equipment_photograph()
        img.paste(photo, (int(img.width * 0.16), int(img.height * 0.42)))
        _handwriting(
            draw,
            (int(img.width * 0.17), int(img.height * 0.80)),
            "check G-06 again after cleaning - AR",
        )

    # Sensor noise.
    pixels = img.load()
    for _ in range(int(img.width * img.height * 0.010)):
        x = random.randrange(img.width)
        y = random.randrange(img.height)
        r, g, b = pixels[x, y]
        n = random.randint(-26, 26)
        pixels[x, y] = (
            max(0, min(255, r + n)),
            max(0, min(255, g + n)),
            max(0, min(255, b + n)),
        )

    img = img.filter(ImageFilter.GaussianBlur(0.4))
    img = img.rotate(random.uniform(-0.5, 0.5), resample=Image.BICUBIC,
                     fillcolor=(250, 247, 238))
    return img


def build_scanned_report(out_path: Path) -> None:
    clean = _text_pdf(REPORT_PAGES)
    scanned = fitz.open()
    for index, page in enumerate(clean):
        image = _scanify(page.get_pixmap(dpi=RENDER_DPI), index)
        # JPEG, like a real scanner would emit — and it keeps the fixture small
        # enough to upload quickly during the demo.
        buffer = FIXTURES / f".page_{index}.jpg"
        image.save(buffer, "JPEG", quality=78)
        new_page = scanned.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, filename=str(buffer))
        buffer.unlink()
    scanned.save(str(out_path))
    scanned.close()
    clean.close()
    print(f"  {out_path.name}: {len(REPORT_PAGES)} scanned pages (no text layer)")


def build_sop(out_path: Path) -> None:
    # Split across two pages at the escalation section, so the demo has to cite
    # more than one page of the procedure.
    head, tail = SOP_TEXT.split("4. ESCALATION PROCESS", 1)
    continued = f"{STAMP}\n\nSOP-CORR-014 (continued)\n\n4. ESCALATION PROCESS{tail}"
    pages = [head.rstrip(), continued]
    doc = _text_pdf(pages, font_size=10)
    doc_pages = doc.page_count
    doc.save(str(out_path))
    doc.close()
    print(f"  {out_path.name}: born-digital SOP, {doc_pages} pages with a text layer")


def build_pid_drawing(out_path: Path) -> None:
    img = Image.new("RGB", (900, 520), (252, 252, 250))
    draw = ImageDraw.Draw(img)
    ink = (24, 28, 36)

    draw.rectangle([12, 12, 888, 508], outline=ink, width=2)
    draw.text((26, 24), "SYNTHETIC P&ID EXTRACT - FOR VISUAL IDENTIFICATION ONLY", fill=ink)
    draw.text((26, 44), "Crude overhead line 12-P-204  |  Unit 3  |  Not for construction",
              fill=(120, 124, 132))

    # Vessel.
    draw.rounded_rectangle([70, 150, 200, 380], radius=40, outline=ink, width=3)
    draw.text((96, 255), "V-301", fill=ink)

    # Line to the elbow.
    draw.line([200, 220, 470, 220], fill=ink, width=3)
    draw.line([470, 220, 470, 360], fill=ink, width=3)
    draw.arc([440, 190, 500, 250], start=270, end=0, fill=ink, width=3)
    draw.text((478, 176), "E-07", fill=(190, 40, 40))
    draw.text((330, 198), "12-P-204", fill=ink)

    # Pump and exchanger.
    draw.ellipse([440, 380, 500, 440], outline=ink, width=3)
    draw.text((456, 402), "P-4", fill=ink)
    draw.line([500, 410, 700, 410], fill=ink, width=3)
    draw.rectangle([700, 350, 830, 470], outline=ink, width=3)
    draw.text((738, 404), "E-12", fill=ink)

    # Instrument bubbles.
    for cx, label in ((300, "TI"), (620, "PI")):
        draw.ellipse([cx - 20, 90, cx + 20, 130], outline=ink, width=2)
        draw.text((cx - 8, 104), label, fill=ink)
        draw.line([cx, 130, cx, 220 if cx == 300 else 410], fill=ink, width=1)

    img.save(out_path)
    print(f"  {out_path.name}: schematic, {img.width}x{img.height}")


def build_readings_workbook(out_path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()

    survey = wb.active
    survey.title = "Thickness Survey"
    survey.append(["grid_point", "nominal_mm", "measured_mm", "wall_loss_mm", "classification"])
    rows = [
        ("G-01", 9.5, 9.4, 0.1, "ROUTINE"),
        ("G-02", 9.5, 9.1, 0.4, "ROUTINE"),
        ("G-03", 9.5, 8.8, 0.7, "ROUTINE"),
        ("G-04", 9.5, 7.9, 1.6, "MONITOR"),
        ("G-05", 9.5, 7.1, 2.4, "ESCALATE"),
        ("G-06", 9.5, 6.8, 2.7, "ESCALATE"),
        ("G-07", 9.5, 7.4, 2.1, "ESCALATE"),
        ("G-08", 9.5, 8.2, 1.3, "MONITOR"),
        ("G-09", 9.5, 9.0, 0.5, "ROUTINE"),
        ("G-10", 9.5, 9.3, 0.2, "ROUTINE"),
        ("G-11", 9.5, 9.4, 0.1, "ROUTINE"),
        ("G-12", 9.5, 9.2, 0.3, "ROUTINE"),
    ]
    for row in rows:
        survey.append(row)

    coating = wb.create_sheet("Coating Condition")
    coating.append(["grid_point", "coating_intact", "product_deposits", "note"])
    for row in [
        ("G-04", "partial", "light", "coating edge lifting"),
        ("G-05", "no", "heavy", "breakdown, corrosion product present"),
        ("G-06", "no", "heavy", "deepest measured loss"),
        ("G-07", "no", "moderate", "breakdown continues along outer radius"),
        ("G-08", "partial", "light", "coating edge lifting"),
    ]:
        coating.append(row)

    schedule = wb.create_sheet("Survey Schedule")
    schedule.append(["component", "interval_hours", "last_survey", "next_survey"])
    for row in [
        ("12-P-204 E-07", 1000, "2026-08-14", "2026-09-25"),
        ("12-P-204 E-08", 5000, "2026-06-02", "2026-12-30"),
        ("12-P-210 spool", 5000, "2026-07-19", "2027-02-14"),
    ]:
        schedule.append(row)

    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"

    wb.save(out_path)
    above = [r for r in rows if r[3] > 2.0]
    print(f"  {out_path.name}: 3 sheets, {len(above)} rows above the 2.0 mm threshold")


def main() -> None:
    print(f"Writing synthetic fixtures into {FIXTURES}")
    build_scanned_report(FIXTURES / "inspection_report.pdf")
    build_sop(FIXTURES / "corrosion_sop.pdf")
    build_pid_drawing(FIXTURES / "pid_drawing.png")
    build_readings_workbook(FIXTURES / "readings_log.xlsx")

    (FIXTURES / "coding_fixture.py").write_text(CODING_FIXTURE, encoding="utf-8")
    print("  coding_fixture.py: off-by-one bug + 3 pytest tests")

    (FIXTURES / "golden_findings.json").write_text(
        json.dumps(GOLDEN_FINDINGS, indent=2), encoding="utf-8"
    )
    print("  golden_findings.json: test oracle")
    print("Done.")


if __name__ == "__main__":
    main()

"""Shared CJK font support for teacher-facing document exports.

PDFs use the bundled Noto Sans SC font, which ReportLab embeds as a subset so
the result remains readable on devices that do not have the font installed.
DOCX files name the same family for East Asian text and provide common Windows
fallbacks; Word does not embed fonts in this export path.
"""

from pathlib import Path

from docx.oxml.ns import qn
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


PDF_FONT = "NotoSansSC"
PDF_FONT_BOLD = "NotoSansSC-Bold"
DOCX_EAST_ASIA_FONT = "Noto Sans SC"
DOCX_FALLBACK_FONT = "Microsoft YaHei"


def _font_path() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "fonts" / "NotoSansSC-VF.ttf"


def register_pdf_fonts():
    """Register the bundled Open Font License CJK font once per process."""
    path = _font_path()
    if not path.is_file():
        raise RuntimeError(f"Chinese PDF font is missing: {path}")
    if PDF_FONT not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT, str(path), subfontIndex=0))
    # The variable font embeds correctly with ReportLab. Use one family for
    # bold/italic requests so CJK glyph coverage is never lost.
    if PDF_FONT_BOLD not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(PDF_FONT_BOLD, str(path), subfontIndex=0))
    return PDF_FONT, PDF_FONT_BOLD


def configure_pdf_canvas(pdf_canvas):
    """Use the embedded CJK family when legacy exporters request core fonts."""
    regular, bold = register_pdf_fonts()
    original_set_font = pdf_canvas.setFont

    def set_font(font_name, size, *args, **kwargs):
        mapped = bold if "Bold" in font_name else regular
        return original_set_font(mapped, size, *args, **kwargs)

    pdf_canvas.setFont = set_font
    # Noto Sans SC covers Chinese and common Latin text, but superscript and
    # subscript Unicode digits are not available in every bundled version.
    # Use equivalent ASCII chemistry notation so a formula never renders as a
    # missing-glyph box in an exported teacher handout.
    substitutions = str.maketrans({
        "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9",
        "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
        "→": "->", "×": "x",
    })
    for method_name in ("drawString", "drawCentredString", "drawRightString"):
        original_draw = getattr(pdf_canvas, method_name)

        def draw(x, y, text, *args, _original=original_draw, **kwargs):
            return _original(x, y, str(text).translate(substitutions), *args, **kwargs)

        setattr(pdf_canvas, method_name, draw)
    return pdf_canvas


def configure_docx_chinese_fonts(document):
    """Set Western and East Asian typefaces on styles, paragraphs, and tables."""
    style_names = ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "List Bullet", "List Number")
    for style_name in style_names:
        try:
            style = document.styles[style_name]
        except KeyError:
            continue
        style.font.name = DOCX_FALLBACK_FONT
        r_pr = style.element.get_or_add_rPr()
        r_fonts = r_pr.rFonts
        if r_fonts is None:
            r_fonts = r_pr._add_rFonts()
        r_fonts.set(qn("w:eastAsia"), DOCX_EAST_ASIA_FONT)
        r_fonts.set(qn("w:ascii"), "Aptos")
        r_fonts.set(qn("w:hAnsi"), "Aptos")

    def apply_runs(paragraphs):
        for paragraph in paragraphs:
            for run in paragraph.runs:
                run.font.name = DOCX_FALLBACK_FONT
                r_pr = run._element.get_or_add_rPr()
                r_fonts = r_pr.rFonts
                if r_fonts is None:
                    r_fonts = r_pr._add_rFonts()
                r_fonts.set(qn("w:eastAsia"), DOCX_EAST_ASIA_FONT)
                r_fonts.set(qn("w:ascii"), "Aptos")
                r_fonts.set(qn("w:hAnsi"), "Aptos")

    apply_runs(document.paragraphs)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                apply_runs(cell.paragraphs)

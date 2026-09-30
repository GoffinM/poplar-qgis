"""A small .xlsx writer: sheets, a few styles, column widths and native Excel charts, without any library.

Only what the reports need. The file is an Office Open XML package (a zip of XML parts), laid out like
the files written by openpyxl, which Excel, LibreOffice and QGIS read. Charts are real Excel charts that
point at cells of the workbook: they can be restyled or extended in Excel.

    book = Workbook()
    sheet = book.sheet("Synthèse")
    sheet.set(1, 1, "Titre", "title")
    sheet.row(3, ["Classe", "Toits"], "header")
    chart = Chart("scatter", "Habitants par toit", "surface (m²)", "habitants")
    chart.add(Series("courbe", sheet.ref(4, 1, 20), sheet.ref(4, 2, 20)))
    sheet.add_chart(chart, col=5, row=3)
    book.save("calage.xlsx")
"""

from __future__ import annotations

import datetime
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CHART_NS = "http://schemas.openxmlformats.org/drawingml/2006/chart"
DRAW_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
SHEET_DRAW_NS = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
EMU_PER_CM = 360000

# Colours of the plugin charter (petrol, ochre, grey)
PETROL, OCHRE, GREY, SAND = "1F6F6A", "C98A36", "7A7A7A", "E8DFC8"
COLOURS = [PETROL, OCHRE, "5B8DB8", GREY, "8C5A9E"]

# Styles: name → (number format id, font id, fill id, border id, wrap)
_NUMBER_FORMATS = {164: "0.0", 165: "0.0%", 166: "#,##0.0", 167: "0.00%"}   # Excel shows "," as the local separator
STYLES: Dict[str, Tuple[int, int, int, int, bool]] = {
    "default": (0, 0, 0, 0, False),
    "title": (0, 1, 0, 0, False),
    "subtitle": (0, 2, 0, 0, False),
    "header": (0, 3, 2, 1, True),
    "integer": (3, 0, 0, 0, False),
    "decimal": (164, 0, 0, 0, False),
    "decimal2": (2, 0, 0, 0, False),
    "percent": (165, 0, 0, 0, False),
    "percent2": (167, 0, 0, 0, False),
    "note": (0, 4, 0, 0, False),              # one line, overflowing to the right (Excel never fits merged cells)
    "bold": (0, 5, 0, 0, False),
    "text": (0, 0, 0, 0, True),
    "label": (0, 5, 3, 0, False),
    "changed": (1, 5, 4, 0, False),
    "total": (3, 5, 0, 2, False),
    "total_decimal": (166, 5, 0, 2, False),
    "warn": (0, 6, 4, 0, True),
}
_STYLE_INDEX = {name: i for i, name in enumerate(STYLES)}
_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SHEET_NAME = re.compile(r"[\[\]:*?/\\]")


def column_letter(col: int) -> str:
    letters = ""
    while col:
        col, rest = divmod(col - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def cell_name(row: int, col: int, absolute: bool = False) -> str:
    dollar = "$" if absolute else ""
    return f"{dollar}{column_letter(col)}{dollar}{row}"


def _text(value: Any) -> str:
    return escape(_BAD_XML.sub("", str(value)))


def sheet_title(name: str, taken: Sequence[str] = ()) -> str:
    """A valid sheet name (31 characters, no []:*?/\\), unique in the workbook."""
    base = _SHEET_NAME.sub("-", name).strip("'") or "Feuille"
    base = base[:31]
    title, number = base, 2
    lower = {t.lower() for t in taken}
    while title.lower() in lower:
        suffix = f" ({number})"
        title = base[:31 - len(suffix)] + suffix
        number += 1
    return title


@dataclass
class Ref:
    """A column range of a sheet: rows ``first`` to ``last`` of column ``col``."""
    sheet: str
    col: int
    first: int
    last: int

    def formula(self) -> str:
        name = self.sheet.replace("'", "''")
        return f"'{name}'!{cell_name(self.first, self.col, True)}:{cell_name(self.last, self.col, True)}"


@dataclass
class Series:
    name: str
    x: Optional[Ref]
    y: Ref
    colour: Optional[str] = None
    line: bool = True
    markers: bool = False
    width_pt: float = 1.75


@dataclass
class Chart:
    kind: str                         # "scatter" (lines or points over numbers) or "bar" (columns)
    title: str
    x_title: str = ""
    y_title: str = ""
    series: List[Series] = field(default_factory=list)
    x_min: Optional[float] = None
    x_max: Optional[float] = None
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    y_format: Optional[str] = None    # for example "0%"
    x_format: Optional[str] = None
    legend: bool = True
    gap_width: int = 40
    width_cm: float = 16.0
    height_cm: float = 8.5

    def add(self, series: Series) -> "Chart":
        self.series.append(series)
        return self


class Sheet:
    def __init__(self, name: str):
        self.name = name
        self.cells: Dict[int, Dict[int, Tuple[Any, str]]] = {}
        self.widths: Dict[int, float] = {}
        self.freeze: Optional[Tuple[int, int]] = None
        self.charts: List[Tuple[Chart, int, int]] = []
        self.merged: List[Tuple[int, int, int, int]] = []
        self.heights: Dict[int, float] = {}

    def set(self, row: int, col: int, value: Any, style: str = "default") -> None:
        if style not in STYLES:
            raise ValueError(f"unknown style {style!r}")
        self.cells.setdefault(row, {})[col] = (value, style)

    def row(self, row: int, values: Sequence[Any], style: str = "default", col: int = 1,
            styles: Optional[Sequence[Optional[str]]] = None) -> None:
        for i, value in enumerate(values):
            chosen = styles[i] if styles is not None and i < len(styles) and styles[i] else style
            self.set(row, col + i, value, chosen)

    def column(self, col: int, first_row: int, values: Sequence[Any], style: str = "default") -> Ref:
        for i, value in enumerate(values):
            self.set(first_row + i, col, value, style)
        return self.ref(col, first_row, first_row + max(0, len(values) - 1))

    def ref(self, col: int, first: int, last: int) -> Ref:
        return Ref(self.name, col, first, last)

    def width(self, col: int, width: float) -> None:
        self.widths[col] = width

    def height(self, row: int, points: float) -> None:
        self.heights[row] = points

    def merge(self, row: int, col: int, last_row: int, last_col: int) -> None:
        self.merged.append((row, col, last_row, last_col))

    def add_chart(self, chart: Chart, col: int, row: int) -> None:
        self.charts.append((chart, col, row))

    # --- XML -------------------------------------------------------------------------

    def xml(self, drawing: bool) -> str:
        parts = [f'<worksheet xmlns="{MAIN}" xmlns:r="{REL}">']
        last_row = max(self.cells) if self.cells else 1
        last_col = max((max(c) for c in self.cells.values() if c), default=1)
        parts.append(f'<dimension ref="A1:{cell_name(last_row, last_col)}"/>')
        parts.append('<sheetViews><sheetView workbookViewId="0">')
        if self.freeze:
            row, col = self.freeze
            top_left = cell_name(row + 1, col + 1)
            attrs = ""
            if col:
                attrs += f' xSplit="{col}"'
            if row:
                attrs += f' ySplit="{row}"'
            pane = "bottomRight" if row and col else ("bottomLeft" if row else "topRight")
            parts.append(f'<pane{attrs} topLeftCell="{top_left}" activePane="{pane}" state="frozen"/>')
            parts.append(f'<selection pane="{pane}" activeCell="{top_left}" sqref="{top_left}"/>')
        parts.append('</sheetView></sheetViews><sheetFormatPr defaultRowHeight="15"/>')
        if self.widths:
            parts.append("<cols>")
            for col in sorted(self.widths):
                parts.append(f'<col min="{col}" max="{col}" width="{self.widths[col]:.2f}" customWidth="1"/>')
            parts.append("</cols>")
        parts.append("<sheetData>")
        for row in sorted(self.cells):
            height = f' ht="{self.heights[row]:.1f}" customHeight="1"' if row in self.heights else ""
            parts.append(f'<row r="{row}"{height}>')
            for col in sorted(self.cells[row]):
                parts.append(self._cell(row, col, *self.cells[row][col]))
            parts.append("</row>")
        parts.append("</sheetData>")
        if self.merged:
            parts.append(f'<mergeCells count="{len(self.merged)}">')
            for r0, c0, r1, c1 in self.merged:
                parts.append(f'<mergeCell ref="{cell_name(r0, c0)}:{cell_name(r1, c1)}"/>')
            parts.append("</mergeCells>")
        parts.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/>')
        if drawing:
            parts.append('<drawing r:id="rId1"/>')
        parts.append("</worksheet>")
        return "".join(parts)

    @staticmethod
    def _cell(row: int, col: int, value: Any, style: str) -> str:
        ref = cell_name(row, col)
        index = _STYLE_INDEX[style]
        s = f' s="{index}"' if index else ""
        if value is None:
            return f'<c r="{ref}"{s}/>'
        if isinstance(value, bool):
            return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if value != value or value in (float("inf"), float("-inf")):   # NaN, infinity: left empty
                return f'<c r="{ref}"{s}/>'
            return f'<c r="{ref}"{s}><v>{repr(float(value)) if isinstance(value, float) else value}</v></c>'
        if isinstance(value, str) and value.startswith("="):
            return f'<c r="{ref}"{s}><f>{_text(value[1:])}</f></c>'
        return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>'


class Workbook:
    def __init__(self, title: str = "", author: str = "Poplar"):
        self.sheets: List[Sheet] = []
        self.title, self.author = title, author

    def sheet(self, name: str) -> Sheet:
        sheet = Sheet(sheet_title(name, [s.name for s in self.sheets]))
        self.sheets.append(sheet)
        return sheet

    def save(self, path: str) -> str:
        if not self.sheets:
            self.sheet("Feuille")
        charts: List[Tuple[int, Chart]] = []        # (sheet index, chart)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
            package.writestr("[Content_Types].xml", self._content_types())
            package.writestr("_rels/.rels", _rels([("officeDocument", "xl/workbook.xml"),
                                                   ("core", "docProps/core.xml"), ("app", "docProps/app.xml")]))
            package.writestr("docProps/core.xml", self._core())
            package.writestr("docProps/app.xml", '<Properties xmlns="http://schemas.openxmlformats.org/'
                                                 'officeDocument/2006/extended-properties">'
                                                 "<Application>Poplar</Application></Properties>")
            package.writestr("xl/workbook.xml", self._workbook())
            package.writestr("xl/_rels/workbook.xml.rels", _rels(
                [("worksheet", f"/xl/worksheets/sheet{i + 1}.xml") for i in range(len(self.sheets))]
                + [("styles", "styles.xml")]))
            package.writestr("xl/styles.xml", _styles())
            drawing_number = 0
            for i, sheet in enumerate(self.sheets, start=1):
                has_drawing = bool(sheet.charts)
                package.writestr(f"xl/worksheets/sheet{i}.xml", sheet.xml(has_drawing))
                if not has_drawing:
                    continue
                drawing_number += 1
                package.writestr(f"xl/worksheets/_rels/sheet{i}.xml.rels",
                                 _rels([("drawing", f"/xl/drawings/drawing{drawing_number}.xml")]))
                anchors, links = [], []
                for chart, col, row in sheet.charts:
                    charts.append((i, chart))
                    number = len(charts)
                    links.append(("chart", f"/xl/charts/chart{number}.xml"))
                    anchors.append(_anchor(len(links), number, chart, col, row))
                    package.writestr(f"xl/charts/chart{number}.xml", _chart_xml(chart))
                package.writestr(f"xl/drawings/drawing{drawing_number}.xml",
                                 f'<xdr:wsDr xmlns:xdr="{SHEET_DRAW_NS}" xmlns:a="{DRAW_NS}" xmlns:c="{CHART_NS}" '
                                 f'xmlns:r="{REL}">{"".join(anchors)}</xdr:wsDr>')
                package.writestr(f"xl/drawings/_rels/drawing{drawing_number}.xml.rels", _rels(links))
        self._chart_count, self._drawing_count = len(charts), drawing_number
        return path

    def _content_types(self) -> str:
        overrides = [("/xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
                     ("/xl/styles.xml", "spreadsheetml.styles+xml")]
        overrides += [(f"/xl/worksheets/sheet{i + 1}.xml", "spreadsheetml.worksheet+xml")
                      for i in range(len(self.sheets))]
        drawings = sum(1 for s in self.sheets if s.charts)
        charts = sum(len(s.charts) for s in self.sheets)
        overrides += [(f"/xl/drawings/drawing{i + 1}.xml", "drawing+xml") for i in range(drawings)]
        overrides += [(f"/xl/charts/chart{i + 1}.xml", "drawingml.chart+xml") for i in range(charts)]
        parts = ['<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                 '<Default Extension="xml" ContentType="application/xml"/>',
                 '<Override PartName="/docProps/core.xml" '
                 'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
                 '<Override PartName="/docProps/app.xml" '
                 'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>']
        for part, kind in overrides:
            parts.append(f'<Override PartName="{part}" ContentType="application/vnd.openxmlformats-officedocument.{kind}"/>')
        parts.append("</Types>")
        return "".join(parts)

    def _core(self) -> str:
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return ('<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
                f"<dc:title>{_text(self.title)}</dc:title><dc:creator>{_text(self.author)}</dc:creator>"
                f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
                f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')

    def _workbook(self) -> str:
        sheets = "".join(f'<sheet name="{_text(s.name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                         for i, s in enumerate(self.sheets))
        return (f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><workbookPr/><bookViews><workbookView activeTab="0"/>'
                f'</bookViews><sheets>{sheets}</sheets><calcPr calcId="124519" fullCalcOnLoad="1"/></workbook>')


_REL_TYPES = {
    "officeDocument": f"{REL}/officeDocument",
    "core": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
    "app": f"{REL}/extended-properties",
    "worksheet": f"{REL}/worksheet",
    "styles": f"{REL}/styles",
    "drawing": f"{REL}/drawing",
    "chart": f"{REL}/chart",
}


def _rels(items: Sequence[Tuple[str, str]]) -> str:
    body = "".join(f'<Relationship Id="rId{i + 1}" Type="{_REL_TYPES[kind]}" Target="{target}"/>'
                   for i, (kind, target) in enumerate(items))
    return f'<Relationships xmlns="{PKG_REL}">{body}</Relationships>'


def _styles() -> str:
    formats = "".join(f'<numFmt numFmtId="{i}" formatCode="{_text(code)}"/>' for i, code in _NUMBER_FORMATS.items())
    fonts = [
        '<font><sz val="10"/><name val="Calibri"/><family val="2"/></font>',                              # 0
        f'<font><b/><sz val="15"/><color rgb="FF{PETROL}"/><name val="Calibri"/><family val="2"/></font>',  # 1 title
        f'<font><b/><sz val="11"/><color rgb="FF{PETROL}"/><name val="Calibri"/><family val="2"/></font>',  # 2
        '<font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font>',    # 3 header
        f'<font><i/><sz val="9"/><color rgb="FF{GREY}"/><name val="Calibri"/><family val="2"/></font>',     # 4 note
        '<font><b/><sz val="10"/><name val="Calibri"/><family val="2"/></font>',                           # 5 bold
        f'<font><b/><sz val="10"/><color rgb="FF8A5A1C"/><name val="Calibri"/><family val="2"/></font>',   # 6 warn
    ]
    fills = [
        '<fill><patternFill patternType="none"/></fill>',
        '<fill><patternFill patternType="gray125"/></fill>',
        f'<fill><patternFill patternType="solid"><fgColor rgb="FF{PETROL}"/><bgColor indexed="64"/></patternFill></fill>',
        '<fill><patternFill patternType="solid"><fgColor rgb="FFEAF2F1"/><bgColor indexed="64"/></patternFill></fill>',
        f'<fill><patternFill patternType="solid"><fgColor rgb="FFF6E7CF"/><bgColor indexed="64"/></patternFill></fill>',
    ]
    borders = [
        "<border><left/><right/><top/><bottom/><diagonal/></border>",
        f'<border><left/><right/><top/><bottom style="thin"><color rgb="FF{PETROL}"/></bottom><diagonal/></border>',
        f'<border><left/><right/><top style="thin"><color rgb="FF{PETROL}"/></top><bottom/><diagonal/></border>',
    ]
    xfs = []
    for number_format, font, fill, border, wrap in STYLES.values():
        attrs = (f'numFmtId="{number_format}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
                 + (' applyNumberFormat="1"' if number_format else "") + (' applyFont="1"' if font else "")
                 + (' applyFill="1"' if fill else "") + (' applyBorder="1"' if border else ""))
        if wrap:
            xfs.append(f'<xf {attrs} applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>')
        else:
            xfs.append(f"<xf {attrs}/>")
    return (f'<styleSheet xmlns="{MAIN}"><numFmts count="{len(_NUMBER_FORMATS)}">{formats}</numFmts>'
            f'<fonts count="{len(fonts)}">{"".join(fonts)}</fonts><fills count="{len(fills)}">{"".join(fills)}</fills>'
            f'<borders count="{len(borders)}">{"".join(borders)}</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def _anchor(rel: int, number: int, chart: Chart, col: int, row: int) -> str:
    cx, cy = int(chart.width_cm * EMU_PER_CM), int(chart.height_cm * EMU_PER_CM)
    return (f"<xdr:oneCellAnchor><xdr:from><xdr:col>{col - 1}</xdr:col><xdr:colOff>0</xdr:colOff>"
            f"<xdr:row>{row - 1}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
            f'<xdr:ext cx="{cx}" cy="{cy}"/><xdr:graphicFrame macro="">'
            f'<xdr:nvGraphicFramePr><xdr:cNvPr id="{number + 1}" name="{_text(chart.title) or "Chart"}"/>'
            "<xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>"
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            f'<a:graphic><a:graphicData uri="{CHART_NS}"><c:chart r:id="rId{rel}"/></a:graphicData></a:graphic>'
            "</xdr:graphicFrame><xdr:clientData/></xdr:oneCellAnchor>")


def _rich(text: str, size: int = 1100, bold: bool = True) -> str:
    return (f'<c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:pPr><a:defRPr sz="{size}" b="{int(bold)}"/></a:pPr>'
            f'<a:r><a:rPr lang="fr-FR" sz="{size}" b="{int(bold)}"/><a:t>{_text(text)}</a:t></a:r></a:p></c:rich></c:tx>')


def _title(text: str, size: int = 1200) -> str:
    return f'<c:title>{_rich(text, size)}<c:overlay val="0"/></c:title>' if text else ""


def _line(colour: str, width_pt: float) -> str:
    return (f'<c:spPr><a:ln w="{int(width_pt * 12700)}" cap="rnd"><a:solidFill><a:srgbClr val="{colour}"/>'
            f'</a:solidFill><a:round/></a:ln></c:spPr>')


def _scaling(minimum: Optional[float], maximum: Optional[float]) -> str:
    extra = (f'<c:max val="{maximum}"/>' if maximum is not None else "") + \
            (f'<c:min val="{minimum}"/>' if minimum is not None else "")
    return f'<c:scaling><c:orientation val="minMax"/>{extra}</c:scaling>'


def _axis(kind: str, axis_id: int, cross_id: int, position: str, title: str, minimum=None, maximum=None,
          number_format: Optional[str] = None, gridlines: bool = False, category: bool = False) -> str:
    fmt = f'<c:numFmt formatCode="{_text(number_format)}" sourceLinked="0"/>' if number_format else ""
    grid = "<c:majorGridlines><c:spPr><a:ln w=\"6350\"><a:solidFill><a:srgbClr val=\"E3E3E3\"/></a:solidFill>" \
           "</a:ln></c:spPr></c:majorGridlines>" if gridlines else ""
    title_xml = _title(title, 1000) if title else ""
    common = (f'<c:axId val="{axis_id}"/>{_scaling(minimum, maximum)}<c:delete val="0"/>'
              f'<c:axPos val="{position}"/>{grid}{title_xml}{fmt}'
              '<c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
              f'<c:crossAx val="{cross_id}"/><c:crosses val="autoZero"/>')
    if category:
        return f'<c:{kind}>{common}<c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/>' \
               f'<c:noMultiLvlLbl val="0"/></c:{kind}>'
    return f'<c:{kind}>{common}<c:crossBetween val="midCat"/></c:{kind}>'


def _series_name(name: str) -> str:
    return f'<c:tx><c:v>{_text(name)}</c:v></c:tx>'


def _chart_xml(chart: Chart) -> str:
    series_xml = []
    for i, series in enumerate(chart.series):
        colour = series.colour or COLOURS[i % len(COLOURS)]
        head = f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/>{_series_name(series.name)}'
        if chart.kind == "bar":
            series_xml.append(
                f'{head}<c:spPr><a:solidFill><a:srgbClr val="{colour}"/></a:solidFill></c:spPr>'
                '<c:invertIfNegative val="0"/>'
                + (f"<c:cat><c:numRef><c:f>{_text(series.x.formula())}</c:f></c:numRef></c:cat>" if series.x else "")
                + f"<c:val><c:numRef><c:f>{_text(series.y.formula())}</c:f></c:numRef></c:val></c:ser>")
            continue
        line = _line(colour, series.width_pt) if series.line else \
            '<c:spPr><a:ln w="19050"><a:noFill/></a:ln></c:spPr>'
        marker = (f'<c:marker><c:symbol val="circle"/><c:size val="6"/><c:spPr><a:solidFill><a:srgbClr val="{colour}"/>'
                  f'</a:solidFill><a:ln><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill></a:ln></c:spPr></c:marker>'
                  if series.markers else '<c:marker><c:symbol val="none"/></c:marker>')
        series_xml.append(
            f"{head}{line}{marker}"
            f"<c:xVal><c:numRef><c:f>{_text(series.x.formula())}</c:f></c:numRef></c:xVal>"
            f"<c:yVal><c:numRef><c:f>{_text(series.y.formula())}</c:f></c:numRef></c:yVal>"
            '<c:smooth val="0"/></c:ser>')
    if chart.kind == "bar":
        plot = (f'<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/><c:varyColors val="0"/>'
                f'{"".join(series_xml)}<c:gapWidth val="{chart.gap_width}"/>'
                '<c:axId val="500010"/><c:axId val="500020"/></c:barChart>'
                + _axis("catAx", 500010, 500020, "b", chart.x_title, number_format=chart.x_format, category=True)
                + _axis("valAx", 500020, 500010, "l", chart.y_title, chart.y_min, chart.y_max, chart.y_format, True))
    elif chart.kind == "scatter":
        plot = (f'<c:scatterChart><c:scatterStyle val="lineMarker"/><c:varyColors val="0"/>{"".join(series_xml)}'
                '<c:axId val="500010"/><c:axId val="500020"/></c:scatterChart>'
                + _axis("valAx", 500010, 500020, "b", chart.x_title, chart.x_min, chart.x_max, chart.x_format)
                + _axis("valAx", 500020, 500010, "l", chart.y_title, chart.y_min, chart.y_max, chart.y_format, True))
    else:
        raise ValueError(f"unknown chart kind {chart.kind!r}")
    legend = '<c:legend><c:legendPos val="b"/><c:overlay val="0"/></c:legend>' if chart.legend else ""
    return (f'<c:chartSpace xmlns:c="{CHART_NS}" xmlns:a="{DRAW_NS}" xmlns:r="{REL}"><c:roundedCorners val="0"/>'
            f'<c:chart>{_title(chart.title)}<c:autoTitleDeleted val="0"/><c:plotArea><c:layout/>{plot}</c:plotArea>'
            f'{legend}<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/></c:chart>'
            '<c:spPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:ln><a:noFill/></a:ln></c:spPr>'
            "</c:chartSpace>")

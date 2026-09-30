"""Excel workbook of a calibration (``calage.xlsx``): figures, tables and native charts, ready to hand over.

Built from the calibration report (``calibration.json``), plus the calibration section of the scenario for
the sources. Sheets:

- **Synthèse**: key figures, one row per regression group and per stratum (gap to the census, factors);
- **Classes – <group>**: the classes (limits, roofs, mean area, inhabitants proposed and retained, population),
  with the people-per-roof curve and the roofs per class as charts;
- **Distribution – <group>**: roofs per m² of roof area and the cumulative shares of roofs and population,
  with their charts;
- **Hypothèses**: the settings of every group and the rules of the model;
- **Sources**: roofs (file or download: dataset, version, date, licence), strata, census, software.

The chart data stay in the sheets, so every chart can be redrawn or restyled in Excel.
"""

from __future__ import annotations

import datetime
import os
from typing import Any, Dict, List, Optional

from . import __version__
from .i18n import format_number, translate
from .xlsx import OCHRE, PETROL, Chart, Series, Workbook

NUMBER = (int, float)


def _t(key: str, language: str, **values) -> str:
    return translate(f"xlsx_{key}", language, **values)


def _limit(spec: Any, resolved: Optional[float], language: str) -> str:
    """« 1er percentile → 10,4 m² », « 12 m² », « aucun »."""
    value = "" if resolved is None else f" → {_num(resolved, language)} m²"
    if spec is None:
        return _t("none", language)
    if isinstance(spec, dict) and "percentile" in spec:
        return _t("percentile", language, p=f"{spec['percentile']:g}") + value
    if isinstance(spec, dict) and "value" in spec:
        return f"{_num(spec['value'], language)} m²"
    if isinstance(spec, NUMBER):
        return f"{_num(spec, language)} m²"
    return str(spec) + value


def build_workbook(report: Dict[str, Any], language: str = "fr", calibration: Optional[Dict[str, Any]] = None,
                   title: str = "") -> Workbook:
    from .scenario import _without_passwords

    calibration = _without_passwords(calibration or {})     # a workbook is handed over: never a password
    book = Workbook(title or _t("title", language, name=""), "Poplar")
    _summary(book.sheet(_t("sheet_summary", language)), report, language, title)
    for name, group in (report.get("groups") or {}).items():
        _classes(book.sheet(_t("sheet_classes", language, group=name)), name, group, language)
        _distribution(book.sheet(_t("sheet_distribution", language, group=name)), name, group, language)
    _hypotheses(book.sheet(_t("sheet_hypotheses", language)), report, calibration, language)
    _sources(book.sheet(_t("sheet_sources", language)), report, calibration, language)
    return book


def write_calibration_workbook(report: Dict[str, Any], path: str, language: str = "fr",
                               calibration: Optional[Dict[str, Any]] = None, title: str = "") -> str:
    return build_workbook(report, language, calibration, title).save(path)


# --- Synthèse -------------------------------------------------------------------------

def _summary(sheet, report, language, title):
    t = lambda key, **v: _t(key, language, **v)  # noqa: E731
    sheet.set(1, 1, t("title", name=f" – {title}" if title else ""), "title")
    sheet.set(2, 1, t("made_by", version=__version__, date=datetime.datetime.now().strftime("%d/%m/%Y %H:%M")),
              "note")
    roofs = report.get("roofs") or {}
    figures = [
        (t("roofs_read"), roofs.get("read"), "integer"),
        (t("roofs_kept"), roofs.get("kept"), "integer"),
        (t("population_total"), report.get("total"), "integer"),
        (t("recalibration"), t("yes") if report.get("recalibrated") else t("no_proposed"), "default"),
        (t("alert_threshold"), (report.get("alert_percent") or 0) / 100, "percent"),
        (t("census_year"), _year(report.get("census_year")), "default"),
        (t("target_year"), _year(report.get("target_year")), "default"),
    ]
    row = 4
    for label, value, style in figures:
        sheet.set(row, 1, label, "label")
        sheet.set(row, 2, value, style)
        row += 1

    row += 1
    sheet.set(row, 1, t("groups"), "subtitle")
    row += 1
    headers = [t("group"), t("strata"), t("roofs"), t("m2_per_person"), t("computed"), t("census"), t("gap"),
               t("alert")]
    sheet.row(row, headers, "header")
    for name, group in (report.get("groups") or {}).items():
        row += 1
        census = group.get("census_at_target")
        sheet.row(row, [name, ", ".join(group.get("strata") or []), group.get("roofs"), group.get("area_per_person"),
                        group.get("population_before_recalibration"), census,
                        None if group.get("gap_percent") is None else group["gap_percent"] / 100,
                        t("yes") if group.get("alert") else ""],
                  styles=["bold", "text", "integer", "decimal2", "integer", "integer", "percent2",
                          "warn" if group.get("alert") else "default"])

    row += 2
    sheet.set(row, 1, t("strata_title"), "subtitle")
    row += 1
    sheet.row(row, [t("stratum"), t("group"), t("roofs"), t("computed"), t("census_target"), t("gap"),
                    t("factor_proposed"), t("factor_applied"), t("population_kept")], "header")
    for name, stratum in (report.get("strata") or {}).items():
        row += 1
        sheet.row(row, [name, stratum.get("group"), stratum.get("roofs"), stratum.get("computed"),
                        stratum.get("census_at_target"),
                        None if stratum.get("gap_percent") is None else stratum["gap_percent"] / 100,
                        stratum.get("proposed_factor"), stratum.get("factor"), stratum.get("population")],
                  styles=["bold", "default", "integer", "integer", "integer", "percent2", "decimal2", "decimal2",
                          "integer"])
    row += 2
    sheet.set(row, 1, t("note_gap"), "note")
    for col, width in enumerate((31, 22, 11, 14, 16, 18, 11, 14, 16), start=1):
        sheet.width(col, width)


# --- Classes --------------------------------------------------------------------------

def _classes(sheet, name, group, language):
    t = lambda key, **v: _t(key, language, **v)  # noqa: E731
    curve = group.get("curve") or {}
    edges = list(curve.get("edges") or [])
    counts = list(group.get("class_counts") or [])
    means = list(group.get("class_means") or [])
    proposed = list(group.get("proposed_values") or [])
    retained = list(group.get("retained_values") or curve.get("values") or [])
    overridden = set(int(i) for i in (group.get("overridden") or []))
    sheet.set(1, 1, t("classes_title", group=name), "title")
    limits = group.get("limits") or {}
    sheet.set(2, 1, t("classes_subtitle", m2=_num(group.get("area_per_person"), language),
                      floor=_num(limits.get("floor"), language), ceiling=_num(limits.get("ceiling"), language),
                      method=t(f"method_{curve.get('method', 'steps')}")), "note")
    head = 4
    sheet.row(head, [t("class"), t("from"), t("to"), t("roofs"), t("mean_area"), t("proposed"), t("retained"),
                     t("population")], "header")
    n = min(len(edges) - 1, len(retained)) if edges else len(retained)
    first = head + 1
    for i in range(n):
        row = first + i
        value = retained[i] if i < len(retained) else None
        sheet.row(row, [i + 1, edges[i] if i < len(edges) else None, edges[i + 1] if i + 1 < len(edges) else None,
                        counts[i] if i < len(counts) else None, means[i] if i < len(means) else None,
                        proposed[i] if i < len(proposed) else None, value],
                  styles=["integer", "decimal", "decimal", "integer", "decimal", "integer",
                          "changed" if i in overridden else "integer"])
        sheet.set(row, 8, f"=D{row}*G{row}", "integer")          # population of the class, kept live in Excel
    last = first + n - 1
    total = last + 1
    sheet.set(total, 1, t("total"), "total")
    for col in (2, 3, 5, 6, 7):
        sheet.set(total, col, None, "total")
    sheet.set(total, 4, f"=SUM(D{first}:D{last})" if n else 0, "total")
    sheet.set(total, 8, f"=SUM(H{first}:H{last})" if n else 0, "total")
    row = total + 2
    notes = [t("excluded_small", n=group.get("excluded_small", 0), floor=_num(limits.get("floor"), language)),
             t("excluded_large", n=group.get("excluded_large", 0), limit=_num(limits.get("exclude_above"), language))]
    if overridden:
        notes.append(t("overridden_note"))
    notes.append(t("population_note"))
    for text in notes:
        sheet.set(row, 1, text, "note")
        row += 1

    # chart data, to the right: the curve sampled every m², and the classes as points
    samples = group.get("samples") or {}
    data_col = 11
    sheet.row(head, [t("chart_data"), None, None, None], "subtitle", col=data_col)
    sheet.row(head + 1, [t("area_m2"), t("inhabitants_curve"), t("class_mean"), t("class_value")], "header",
              col=data_col)
    areas = list(samples.get("area") or [])
    people = list(samples.get("inhabitants") or [])
    curve_x = sheet.column(data_col, head + 2, areas, "decimal")
    curve_y = sheet.column(data_col + 1, head + 2, people, "decimal")
    points_x = sheet.column(data_col + 2, head + 2, means[:n], "decimal")
    points_y = sheet.column(data_col + 3, head + 2, retained[:n], "integer")
    chart = Chart("scatter", t("chart_curve", group=name), t("axis_area"), t("axis_inhabitants"), y_min=0,
                  x_min=0, x_max=_round_up(areas[-1] if areas else (edges[-1] if edges else 100)), x_format="0",
                  y_format="0")
    if areas:
        chart.add(Series(t("inhabitants_curve"), curve_x, curve_y, PETROL))
    if n:
        chart.add(Series(t("class_value"), points_x, points_y, OCHRE, line=False, markers=True))
    sheet.add_chart(chart, col=1, row=row + 1)
    if n:
        roofs_chart = Chart("bar", t("chart_roofs_per_class", group=name), t("class"), t("roofs"), legend=False,
                            y_format="#,##0")
        roofs_chart.add(Series(t("roofs"), sheet.ref(1, first, last), sheet.ref(4, first, last), PETROL))
        sheet.add_chart(roofs_chart, col=1, row=row + 19)
    for col, width in enumerate((9, 10, 10, 10, 15, 16, 16, 14), start=1):
        sheet.width(col, width)
    for col in range(data_col, data_col + 4):
        sheet.width(col, 15)
    sheet.freeze = (head, 0)


# --- Distribution ---------------------------------------------------------------------

def _distribution(sheet, name, group, language):
    t = lambda key, **v: _t(key, language, **v)  # noqa: E731
    sheet.set(1, 1, t("distribution_title", group=name), "title")
    sheet.set(2, 1, t("distribution_subtitle"), "note")
    head = 4
    distribution = group.get("distribution") or {}
    cumulative = group.get("cumulative") or {}
    sheet.row(head, [t("area_bin"), t("roofs")], "header")
    # bins of 1 m², shown by their lower bound (0, 1, 2… m²)
    x = sheet.column(1, head + 1, [int(a) for a in distribution.get("area") or []], "integer")
    y = sheet.column(2, head + 1, list(distribution.get("count") or []), "integer")
    sheet.row(head, [t("area_up_to"), t("share_roofs"), t("share_population")], "header", col=4)
    cx = sheet.column(4, head + 1, list(cumulative.get("area") or []), "decimal")
    roofs = sheet.column(5, head + 1, list(cumulative.get("roofs") or []), "percent")
    people = sheet.column(6, head + 1, list(cumulative.get("population") or []), "percent")
    limits = group.get("limits") or {}
    top = _round_up(max(list(distribution.get("area") or [100])))
    if distribution.get("area"):
        chart = Chart("bar", t("chart_distribution", group=name), t("axis_area"), t("axis_roofs"), legend=False,
                      gap_width=0, x_format="0")
        chart.add(Series(t("roofs"), x, y, PETROL))
        sheet.add_chart(chart, col=8, row=head)
    if cumulative.get("area"):
        chart = Chart("scatter", t("chart_cumulative", group=name), t("axis_area"), t("axis_share"), y_min=0,
                      y_max=1, y_format="0%", x_min=0, x_max=top, x_format="0")
        chart.add(Series(t("share_roofs"), cx, roofs, PETROL))
        chart.add(Series(t("share_population"), cx, people, OCHRE))
        sheet.add_chart(chart, col=8, row=head + 19)
    sheet.set(head + 38, 8, t("limits_note", floor=_num(limits.get("floor"), language), ceiling=_num(limits.get("ceiling"), language)),
              "note")
    for col, width in ((1, 14), (2, 10), (3, 3), (4, 14), (5, 16), (6, 18)):
        sheet.width(col, width)
    sheet.freeze = (head, 0)


# --- Hypothèses -------------------------------------------------------------------------

def _hypotheses(sheet, report, calibration, language):
    t = lambda key, **v: _t(key, language, **v)  # noqa: E731
    sheet.set(1, 1, t("hypotheses_title"), "title")
    row = 3
    sheet.set(row, 1, t("model_title"), "subtitle")
    for key in ("model_1", "model_2", "model_3", "model_4", "model_5"):
        row += 1
        text = t(key)
        sheet.set(row, 1, text, "text")
        sheet.merge(row, 1, row, 4)
        sheet.height(row, 15 * (1 + len(text) // 110))      # merged cells are never fitted: height by length
    row += 2
    sheet.set(row, 1, t("general_title"), "subtitle")
    rate = calibration.get("gap_growth_rate")
    for label, value in ((t("census_year"), _year(report.get("census_year"))),
                         (t("target_year"), _year(report.get("target_year"))),
                         (t("gap_rate"), t("scenario_rate") if rate is None else rate),
                         (t("recalibration"), t("yes") if report.get("recalibrated") else t("no_proposed")),
                         (t("alert_threshold"), f"± {format_number(float(report.get('alert_percent', 2)), language)} %"),
                         (t("buildings_year"), report.get("buildings_year") or "–")):
        row += 1
        sheet.row(row, [label, value], styles=["label", "default"])
    for name, group in (report.get("groups") or {}).items():
        settings = group.get("settings") or {}
        classes = settings.get("classes") or {}
        limits = group.get("limits") or {}
        row += 2
        sheet.set(row, 1, t("group_settings", group=name), "subtitle")
        values = [
            (t("curve_method"), t(f"method_{settings.get('method', 'steps')}")),
            (t("cut"), t(f"cut_{classes.get('method', 'breaks')}")),
            (t("class_count"), classes.get("count")),
            (t("floor"), _limit(settings.get("floor"), limits.get("floor"), language)),
            (t("ceiling"), _limit(settings.get("ceiling"), limits.get("ceiling"), language)),
            (t("exclude_above"), _limit(settings.get("exclude_above"), None, language)),
            (t("values_from"), t(f"values_from_{settings.get('values_from', 'area_per_person')}")),
            (t("m2_per_person"), f"{_num(group.get('area_per_person'), language)} m²"
             + (f" ({t('fitted')})" if group.get("area_per_person_fitted") else f" ({t('entered')})")),
            (t("per_roof"), t("per_roof_range", low=settings.get("min_per_roof", 1),
                              high=settings.get("max_per_roof", 15))),
            (t("overrides"), ", ".join(f"{t('class')} {int(k) + 1} = {v:g}"
                                       for k, v in sorted((settings.get("overrides") or {}).items(),
                                                          key=lambda kv: int(kv[0]))) or "–"),
        ]
        for label, value in values:
            row += 1
            sheet.row(row, [label, value], styles=["label", "default"])
    sheet.width(1, 36)
    sheet.width(2, 44)
    sheet.width(3, 20)
    sheet.width(4, 20)


# --- Sources ----------------------------------------------------------------------------

def _sources(sheet, report, calibration, language):
    t = lambda key, **v: _t(key, language, **v)  # noqa: E731
    sheet.set(1, 1, t("sources_title"), "title")
    roofs = report.get("roofs") or {}
    buildings = calibration.get("buildings") or {}
    download = roofs.get("download") or {}
    rows: List[tuple] = [("subtitle", t("roofs_title"), None),
                         ("label", t("roofs_file"), _path(buildings.get("source"))),
                         ("label", t("area_field"), buildings.get("area_field") or t("area_computed")),
                         ("label", t("roofs_read"), roofs.get("read")),
                         ("label", t("roofs_kept"), roofs.get("kept"))]
    for key in ("low_confidence", "usage_zero", "outside_study_area", "without_stratum"):
        if roofs.get(key):
            rows.append(("label", t(f"excluded_{key}"), roofs[key]))
    if download:
        rows += [("subtitle", t("download_title"), None),
                 ("label", t("dataset"), download.get("dataset")),
                 ("label", t("release"), download.get("release") or "–"),
                 ("label", t("download_date"), str(download.get("date", ""))[:10]),
                 ("label", t("imagery_year"), download.get("imagery_year") or "–"),
                 ("label", t("licence"), download.get("licence")),
                 ("label", t("attribution"), download.get("attribution"))]
        for source, count in (download.get("by_source") or {}).items():
            rows.append(("label", t("from_source", source=source), count))
    strata = calibration.get("strata") or {}
    rows += [("subtitle", t("strata_title"), None),
             ("label", t("strata_layer"), _path(strata.get("source")) if strata else t("whole_area")),
             ("label", t("strata_field"), strata.get("field") or "–"),
             ("label", t("group_field"), strata.get("group_field") or "–")]
    census = calibration.get("census") or {}
    rows.append(("subtitle", t("census_title"), None))
    if strata.get("census_field"):
        rows.append(("label", t("census_field"), strata["census_field"]))
    for name, value in census.items():
        rows.append(("label", name, value))
    rows += [("subtitle", t("software_title"), None),
             ("label", "Poplar", __version__),
             ("label", t("made_on"), datetime.date.today().strftime("%d/%m/%Y"))]
    row = 2
    for style, label, value in rows:
        row += 2 if style == "subtitle" else 1
        if style == "subtitle":
            sheet.set(row, 1, label, "subtitle")
            continue
        sheet.row(row, [label, value], styles=["label", "integer" if isinstance(value, NUMBER) else "text"])
    sheet.width(1, 36)
    sheet.width(2, 80)


# --- helpers ----------------------------------------------------------------------------

def _num(value, language: str = "fr") -> str:
    """119,7 stays 119,7 and 450 stays 450 (never rounded away)."""
    if value is None:
        return "–"
    value = float(value)
    return format_number(value, language, 0 if value.is_integer() else (1 if abs(value * 10 - round(value * 10)) < 1e-9
                                                                          else 2))


def _year(value):
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _path(value) -> str:
    if not value:
        return "–"
    if str(value).upper().startswith("PG:"):
        return str(value)                      # a database: the password is never in the scenario
    return os.path.normpath(str(value))


def _round_up(value: float) -> float:
    step = 50 if value > 200 else 10
    return float(int(value / step + 0.999) * step)

"""Automatic report outside QGIS (plan of phase 6, step 6.6).

``python -m engine report <folder>`` turns the JSON reports of a run
(``report.json``, ``calibration.json``, ``scenario_used.json``) into one
self-contained HTML page: tables and SVG charts, no external resource, no
dependency. It opens in any browser and prints to PDF. Every run also
writes it (``report.html``).
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .i18n import DEFAULT_LANGUAGE, format_number, translate

PETROL, OCHRE, GREY, SAND = "#1f6f6a", "#c98a36", "#5c6e6c", "#dcecea"

STYLE = """
body { font-family: "Segoe UI", system-ui, sans-serif; color: #1d2b2a; margin: 0; background: #ffffff; }
main { max-width: 980px; margin: 0 auto; padding: 24px 20px 48px; }
header { border-bottom: 3px solid #1f6f6a; padding-bottom: 10px; margin-bottom: 18px; }
h1 { font-size: 22px; margin: 0; } h2 { font-size: 16px; color: #1f6f6a; margin: 26px 0 8px; }
h3 { font-size: 14px; margin: 16px 0 6px; }
.sub { color: #5c6e6c; margin: 4px 0 0; }
.figures { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }
.figures div { border: 1px solid #d5dedc; border-radius: 4px; padding: 8px 10px; }
.figures b { display: block; font-size: 18px; font-variant-numeric: tabular-nums; }
.figures span { color: #5c6e6c; font-size: 12px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; margin: 6px 0; }
th, td { border-bottom: 1px solid #d5dedc; padding: 4px 6px; text-align: right; }
th { background: #f6f8f7; color: #5c6e6c; font-weight: 600; }
th:first-child, td:first-child { text-align: left; }
.alert { color: #a4452a; font-weight: 600; } .ok { color: #1f6f6a; font-weight: 600; }
.mod { background: #f6e7cf; }
ul { margin: 4px 0; padding-left: 20px; } li { margin: 2px 0; }
svg text { font-size: 11px; fill: #5c6e6c; font-family: "Segoe UI", system-ui, sans-serif; }
.legend { color: #5c6e6c; font-size: 12px; }
footer { color: #5c6e6c; font-size: 12px; margin-top: 30px; border-top: 1px solid #d5dedc; padding-top: 8px; }
@media print { main { padding: 0; } h2 { break-after: avoid; } svg, table { break-inside: avoid; } }
"""


def _load(path: str) -> Optional[Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _nice_ticks(low: float, high: float, count: int = 5) -> List[float]:
    span = max(high - low, 1e-9)
    raw = span / count
    magnitude = 10 ** int(f"{raw:e}".split("e")[1])
    step = min((m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw), default=raw)
    first = step * int(low // step)
    ticks, value = [], first
    while value <= high + step * 0.01:
        if value >= low - 1e-9:
            ticks.append(value)
        value += step
    return ticks


class _Chart:
    """Minimal SVG chart: x and y scales, grid, lines, bars, steps."""

    def __init__(self, width=900, height=260, x=(0.0, 1.0), y=(0.0, 1.0), margins=(56, 14, 56, 36)):
        self.w, self.h = width, height
        self.left, self.top, self.right, self.bottom = margins
        self.x0, self.x1 = x
        self.y0, self.y1 = y
        self.parts: List[str] = []

    def sx(self, x):
        return self.left + (x - self.x0) / max(self.x1 - self.x0, 1e-12) * (self.w - self.left - self.right)

    def sy(self, y):
        return self.h - self.bottom - (y - self.y0) / max(self.y1 - self.y0, 1e-12) * (self.h - self.top - self.bottom)

    def axes(self, x_label="", y_label="", y_format=lambda v: f"{v:g}", x_format=lambda v: f"{v:g}", right=False,
             whole_x=False):
        for value in _nice_ticks(self.y0, self.y1):
            y = self.sy(value)
            self.parts.append(f'<line x1="{self.left}" x2="{self.w - self.right}" y1="{y:.1f}" y2="{y:.1f}" '
                              f'stroke="#d5dedc"/>')
            x, anchor = (self.w - self.right + 6, "start") if right else (self.left - 6, "end")
            self.parts.append(f'<text x="{x}" y="{y + 4:.1f}" text-anchor="{anchor}">{_esc(y_format(value))}</text>')
        for value in _nice_ticks(self.x0, self.x1, 8):
            if whole_x and abs(value - round(value)) > 1e-9:
                continue
            self.parts.append(f'<text x="{self.sx(value):.1f}" y="{self.h - self.bottom + 15}" '
                              f'text-anchor="middle">{_esc(x_format(value))}</text>')
        if x_label:
            self.parts.append(f'<text x="{(self.left + self.w - self.right) / 2}" y="{self.h - 4}" '
                              f'text-anchor="middle">{_esc(x_label)}</text>')
        if y_label:
            self.parts.append(f'<text x="{self.left if not right else self.w - 4}" y="{self.top - 2}" '
                              f'text-anchor="{"start" if not right else "end"}">{_esc(y_label)}</text>')

    def line(self, xs, ys, colour, width=2.0, dash=None):
        points = " ".join(f"{self.sx(x):.1f},{self.sy(y):.1f}" for x, y in zip(xs, ys))
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="{width}"{extra}/>')

    def bars(self, xs, heights, width, colour):
        for x, h in zip(xs, heights):
            if h > 0:
                y = self.sy(h)
                self.parts.append(f'<rect x="{self.sx(x - width / 2):.1f}" y="{y:.1f}" '
                                  f'width="{max(self.sx(x + width / 2) - self.sx(x - width / 2) - 0.4, 0.4):.1f}" '
                                  f'height="{self.sy(self.y0) - y:.1f}" fill="{colour}"/>')

    def vline(self, x, colour, dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{self.sx(x):.1f}" x2="{self.sx(x):.1f}" y1="{self.top}" '
                          f'y2="{self.h - self.bottom}" stroke="{colour}" stroke-width="1.5"{extra}/>')

    def svg(self, title=""):
        return (f'<svg viewBox="0 0 {self.w} {self.h}" width="100%" role="img" aria-label="{_esc(title)}">'
                + "".join(self.parts) + "</svg>")


def _t(code: str, language: str, **values) -> str:
    return translate(f"html_{code}", language, **values)


def _figures(items: Sequence[Tuple[str, str]]) -> str:
    return '<div class="figures">' + "".join(f"<div><span>{_esc(k)}</span><b>{_esc(v)}</b></div>" for k, v in items) \
        + "</div>"


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]], classes: Sequence[Sequence[str]] = ()) -> str:
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = []
    for i, row in enumerate(rows):
        cells = []
        for j, value in enumerate(row):
            css = classes[i][j] if i < len(classes) and j < len(classes[i]) else ""
            cells.append(f'<td class="{css}">{_esc(value)}</td>' if css else f"<td>{_esc(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _population_section(report: Dict[str, Any], language: str) -> str:
    steps = report.get("steps") or []
    n = lambda v, d=0: format_number(float(v), language, d)  # noqa: E731
    parts = [f"<h2>{_esc(_t('population', language))}</h2>"]
    if steps:
        xs = [steps[0]["start"]] + [s["end"] for s in steps]
        ys = [steps[0]["population_before_growth"]] + [s["population_after_migration"] for s in steps]
        chart = _Chart(x=(min(xs), max(xs)), y=(0, max(ys) * 1.08))
        chart.axes(_t("year", language), _t("inhabitants", language), y_format=lambda v: n(v),
                   x_format=lambda v: f"{v:.0f}", whole_x=True)
        chart.line(xs, ys, PETROL, 2.5)
        parts.append(chart.svg(_t("population", language)))
        rows = [(f"{s['start']:g} → {s['end']:g}", n(s["population_before_growth"]), n(s["population_after_growth"]),
                 n(s["population_after_migration"]), n(s["moved"]), n(s["unallocated"]),
                 translate(f"status_{s['status']}", language)) for s in steps]
        parts.append(_table([_t(c, language) for c in ("step", "before", "after_growth", "after_migration", "moved",
                                                       "unallocated", "status")], rows))
    return "".join(parts)


def _messages_section(report: Dict[str, Any], language: str) -> str:
    items = [m.get("text", m.get("code", "")) for m in (report.get("warnings") or []) + (report.get("events") or [])]
    if not items:
        return ""
    return f"<h2>{_esc(_t('warnings', language))}</h2><ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


LINE_COLOURS = [PETROL, OCHRE, "#7a4e8c", "#3f7fb3", "#a4452a", GREY]


def _polygons_section(indicators: Dict[str, Any], language: str) -> str:
    """Free strata mode: plausibility indicators (plausibilite.json)."""
    n = lambda v, d=0: "–" if v is None else format_number(float(v), language, d)  # noqa: E731
    horizons = indicators.get("horizons") or []
    parts = [f"<h2>{_esc(_t('polygons', language))}</h2>",
             f"<p class=\"legend\">{_esc(_t('polygons_intro', language, cap=n(indicators.get('speed_cap_m_per_year'))))}</p>"]
    if not horizons:
        return "".join(parts)
    last = max(r["year_end"] for r in horizons)
    final = [r for r in horizons if r["year_end"] == last]
    urban_final = [r for r in final if r.get("urban")]
    parts.append(_figures([
        (_t("polygons_count", language), n(len({r["id"] for r in final}))),
        (_t("polygons_urban_area", language), f"{n(sum(r['area_end_km2'] for r in urban_final), 2)} km²"),
        (_t("polygons_colonised", language), n(indicators.get("colonised_cells", 0))),
        (_t("polygons_nuclei", language), n(len(indicators.get("new_nuclei") or []))),
    ]))
    # Area of each urban polygon over time.
    series: Dict[int, List[Tuple[float, float]]] = {}
    for r in sorted(horizons, key=lambda r: r["year_end"]):
        if r.get("urban"):
            points = series.setdefault(r["id"], [(r["year_start"], r["area_start_km2"])])
            points.append((r["year_end"], r["area_end_km2"]))
    if series:
        xs = [x for points in series.values() for x, _ in points]
        ys = [y for points in series.values() for _, y in points]
        chart = _Chart(x=(min(xs), max(xs)), y=(0, max(ys) * 1.1 or 1))
        chart.axes(_t("year", language), _t("polygons_area", language), y_format=lambda v: n(v, 1),
                   x_format=lambda v: f"{v:.0f}", whole_x=True)
        for i, (polygon, points) in enumerate(sorted(series.items())):
            chart.line([x for x, _ in points], [y for _, y in points], LINE_COLOURS[i % len(LINE_COLOURS)], 2.2)
        parts.append(chart.svg(_t("polygons_area_chart", language)))
        parts.append('<p class="legend">' + " · ".join(
            f'<span style="color:{LINE_COLOURS[i % len(LINE_COLOURS)]}">■</span> {polygon}'
            for i, polygon in enumerate(sorted(series))) + "</p>")
    rows, classes = [], []
    for r in sorted(horizons, key=lambda r: (r["id"], r["year_start"])):
        if not r.get("urban"):
            continue
        rows.append((f"{r['year_start']} → {r['year_end']}", f"{r['id']} – {r['stratum']}",
                     n(r["area_end_km2"], 2), n(r["front_speed_m_per_year"], 0),
                     _t("reading_" + r["reading"], language),
                     f"{n(r['density_p10'])} / {n(r['density_p50'])} / {n(r['density_p90'])}",
                     n(None if r["saturated_share"] is None else 100 * r["saturated_share"], 0) + " %",
                     n(r["compactness"], 2), _t("yes" if r["capped"] else "no", language)))
        classes.append(["", "", "", "alert" if r["capped"] else "", "", "", "", "", "alert" if r["capped"] else ""])
    if rows:
        parts.append(_table([_t(c, language) for c in ("polygons_horizon", "polygons_id", "polygons_area",
                                                       "polygons_front", "polygons_reading", "polygons_density",
                                                       "polygons_saturated", "polygons_compactness",
                                                       "polygons_capped")], rows, classes))
    nuclei = indicators.get("new_nuclei") or []
    if nuclei:
        parts.append(f"<h3>{_esc(_t('polygons_nuclei', language))}</h3>")
        parts.append(_table([_t("polygons_id", language), _t("year", language), _t("inhabitants", language),
                             _t("polygons_to_check", language)],
                            [(p["id"], p["year"], n(p["population"]), ", ".join(p["to_check"]) or "–") for p in nuclei]))
    reclass = [r for r in indicators.get("reclassification") or [] if r["year"] == max(
        x["year"] for x in indicators.get("reclassification") or [{"year": 0}])]
    if reclass:
        parts.append(f"<h3>{_esc(_t('polygons_reclass', language))}</h3>")
        parts.append(_table([_t("polygons_admin", language), _t("polygons_effect", language)],
                            [(r["admin"], n(r["effect"])) for r in reclass]))
    balance = indicators.get("mass_balance") or []
    if balance:
        parts.append(f"<h3>{_esc(_t('polygons_balance', language))}</h3>")
        parts.append(_table([_t("polygons_horizon", language), _t("before", language), _t("after_growth", language),
                             _t("unallocated", language), _t("after_migration", language),
                             _t("polygons_gap", language)],
                            [(f"{b['year_start']} → {b['year_end']}", n(b["start"]), n(b["growth"]),
                              n(b["unallocated"]), n(b["end"]), n(b["gap"], 3)) for b in balance],
                            [["", "", "", "", "", "ok" if abs(b["gap"]) < 0.5 else "alert"] for b in balance]))
    return "".join(parts)


def _calibration_section(calibration: Dict[str, Any], language: str) -> str:
    n = lambda v, d=0: "–" if v is None else format_number(float(v), language, d)  # noqa: E731
    roofs = calibration.get("roofs") or {}
    parts = [f"<h2>{_esc(_t('calibration', language))}</h2>"]
    parts.append(_figures([
        (_t("roofs_read", language), n(roofs.get("read"))), (_t("roofs_kept", language), n(roofs.get("kept"))),
        (_t("population_from_roofs", language), n(calibration.get("total"))),
        (_t("recalibration", language), _t("applied" if calibration.get("recalibrated") else "not_applied", language)),
    ]))
    excluded = [(_t(k, language), n(roofs[k])) for k in ("low_confidence", "usage_zero", "outside_study_area",
                                                          "without_stratum") if roofs.get(k)]
    if excluded or roofs.get("unknown_usage"):
        parts.append("<ul>" + "".join(f"<li>{_esc(k)} : {_esc(v)}</li>" for k, v in excluded))
        if roofs.get("unknown_usage"):
            parts.append(f"<li>{_esc(_t('unknown_usage', language))} : {_esc(', '.join(roofs['unknown_usage']))}</li>")
        parts.append("</ul>")
    download = roofs.get("download")
    if download:
        parts.append(f"<p>{_esc(_t('roofs_source', language, dataset=download.get('dataset', ''), date=str(download.get('date', ''))[:10], licence=download.get('licence', '')))}</p>")
    strata = calibration.get("strata") or {}
    if strata:
        rows, classes = [], []
        for name, s in strata.items():
            gap = s.get("gap_percent")
            rows.append((name, s.get("group", ""), n(s.get("roofs")), n(s.get("computed")), n(s.get("census_at_target")),
                         "–" if gap is None else f"{gap:+.2f} %", n(s.get("proposed_factor"), 3), n(s.get("factor"), 3)))
            classes.append(["", "", "", "", "", "alert" if s.get("alert") else ("ok" if gap is not None else ""), "", ""])
        parts.append(f"<h3>{_esc(_t('strata', language))}</h3>")
        parts.append(_table([_t(c, language) for c in ("stratum", "group", "roofs", "computed", "census", "gap",
                                                       "proposed_factor", "factor")], rows, classes))
    for name, group in (calibration.get("groups") or {}).items():
        parts.append(_group_section(name, group, language, calibration.get("alert_percent", 2.0)))
    return "".join(parts)


def _group_section(name: str, group: Dict[str, Any], language: str, alert: float) -> str:
    n = lambda v, d=0: "–" if v is None else format_number(float(v), language, d)  # noqa: E731
    curve = group.get("curve") or {}
    edges = curve.get("edges") or []
    parts = [f"<h3>{_esc(_t('group_title', language, name=name))}</h3>"]
    limits = group.get("limits") or {}
    gap = group.get("gap_percent")
    parts.append(_figures([
        (_t("roofs", language), n(group.get("roofs"))),
        (_t("area_per_person", language), n(group.get("area_per_person"), 2) + " m²"
         if group.get("area_per_person") else "–"),
        (_t("floor", language), n(limits.get("floor"), 1) + " m²" if limits.get("floor") is not None else "–"),
        (_t("ceiling", language), n(limits.get("ceiling"), 1) + " m²" if limits.get("ceiling") is not None else "–"),
        (_t("gap", language), "–" if gap is None else f"{gap:+.2f} %"),
    ]))
    if gap is not None and abs(gap) > alert:
        parts.append(f'<p class="alert">{_esc(_t("alert", language, alert=n(alert)))}</p>')
    distribution = group.get("distribution") or {}
    if distribution.get("area"):
        areas, counts = distribution["area"], distribution["count"]
        top = max(edges[-1] * 1.3 if edges else areas[-1], 20)
        keep = [i for i, a in enumerate(areas) if a <= top]
        chart = _Chart(x=(0, top), y=(0, max([counts[i] for i in keep] + [1]) * 1.05))
        chart.axes(_t("roof_area", language), _t("roofs_per_m2", language))
        chart.bars([areas[i] for i in keep], [counts[i] for i in keep], 1.0, SAND)
        samples = group.get("samples") or {}
        values = group.get("retained_values") or curve.get("values") or [1]
        if samples.get("area"):
            scale = chart.y1 / max(max(values) * 1.15, 1)
            xs = [a for a in samples["area"] if a <= top]
            chart.line(xs, [samples["inhabitants"][i] * scale for i in range(len(xs))], PETROL, 2.5)
            for value in _nice_ticks(0, max(values) * 1.15):
                chart.parts.append(f'<text x="{chart.w - chart.right + 6}" y="{chart.sy(value * scale) + 4:.1f}">'
                                   f'{value:g}</text>')
        for edge in edges:
            if edge <= top:
                chart.vline(edge, OCHRE)
        parts.append(chart.svg(name))
        parts.append(f'<p class="legend">{_esc(_t("legend_distribution", language))}</p>')
    cumulative = group.get("cumulative") or {}
    if cumulative.get("area"):
        chart = _Chart(height=220, x=(0, cumulative["area"][-1]), y=(0, 1))
        chart.axes(_t("roof_area", language), "", y_format=lambda v: f"{v * 100:.0f} %")
        chart.line(cumulative["area"], cumulative["roofs"], GREY, 2)
        chart.line(cumulative["area"], cumulative["population"], PETROL, 2.5)
        for edge in edges:
            if edge <= cumulative["area"][-1]:
                chart.vline(edge, OCHRE)
        parts.append(chart.svg(name))
        parts.append(f'<p class="legend">{_esc(_t("legend_cumulative", language))}</p>')
    counts = group.get("class_counts") or []
    means = group.get("class_means") or []
    proposed = group.get("proposed_values") or curve.get("values") or []
    retained = group.get("retained_values") or proposed
    overridden = set(group.get("overridden") or [])
    rows, classes = [], []
    for k in range(max(len(edges) - 1, 0)):
        rows.append((k + 1, n(edges[k], 1), n(edges[k + 1], 1), n(counts[k] if k < len(counts) else None),
                     n(means[k] if k < len(means) else None, 1), n(proposed[k] if k < len(proposed) else None, 1),
                     n(retained[k] if k < len(retained) else None, 1)))
        classes.append(["", "", "", "", "", "", "mod" if k in overridden else ""])
    parts.append(_table([_t(c, language) for c in ("class", "from", "to", "roofs", "mean", "proposed", "retained")],
                        rows, classes))
    if overridden:
        parts.append(f'<p class="legend">{_esc(_t("overridden", language))}</p>')
    regression = group.get("regression")
    if regression:
        parts.append(f"<p>{_esc(_t('regression', language, r2=n(regression['r2'], 3), rmse=n(regression['rmse']), mape=n(regression['mape'] * 100, 1)))}</p>")
    diagnostics = group.get("diagnostics") or {}
    if diagnostics:
        parts.append(f"<p class=\"legend\">{_esc(_t('diagnostics', language, monotone=_t('yes' if diagnostics.get('monotone') else 'no', language), capped=n(100 * diagnostics.get('share_capped', 0), 1)))}</p>")
    return "".join(parts)


def build_html_report(directory: str, language: Optional[str] = None) -> str:
    """HTML page of a run folder (report.json required)."""
    report = _load(os.path.join(directory, "report.json"))
    if report is None:
        raise FileNotFoundError(os.path.join(directory, "report.json"))
    scenario = _load(os.path.join(directory, "scenario_used.json")) or {}
    calibration = _load(os.path.join(directory, "calibration.json"))
    language = language or scenario.get("language") or DEFAULT_LANGUAGE
    n = lambda v, d=0: format_number(float(v), language, d)  # noqa: E731
    time = scenario.get("time") or {}
    name = report.get("name") or scenario.get("name") or "–"
    parts = [f"<header><h1>{_esc(_t('title', language, name=name))}</h1>"
             f"<p class=\"sub\">{_esc(scenario.get('description') or '')}</p>"
             f"<p class=\"sub\">{_esc(_t('period', language, start=f"{time.get('base_year', 0):g}", end=f"{time.get('end_year', 0):g}"))}"
             f" · {_esc(translate('status_' + report.get('status', 'failed'), language))}</p></header>"]
    parts.append(_figures([
        (_t("start_population", language), n(report.get("base_population", 0))),
        (_t("end_population", language), n(report.get("final_population", 0))),
        (_t("cells", language), n(report.get("cells", 0))),
        (_t("units", language), n(report.get("units", 0))),
        (_t("cell_size", language), f"{float(scenario.get('cell_size', 0)):g} m"),
        (_t("duration", language), f"{report.get('duration_s', 0):g} s"),
    ]))
    parts.append(_messages_section(report, language))
    parts.append(_population_section(report, language))
    if calibration:
        parts.append(_calibration_section(calibration, language))
    indicators = _load(os.path.join(directory, "plausibilite.json"))
    if indicators:
        parts.append(_polygons_section(indicators, language))
    generated = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts.append(f"<footer>{_esc(_t('footer', language, date=generated, engine=report.get('engine_version', '?'), gdal=report.get('gdal_version', '?')))}</footer>")
    return (f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_esc(_t('title', language, name=name))}</title><style>{STYLE}</style></head>"
            f"<body><main>{''.join(parts)}</main></body></html>")


def write_html_report(directory: str, language: Optional[str] = None) -> str:
    path = os.path.join(directory, "report.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_html_report(directory, language))
    return path

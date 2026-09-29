"""Spreadsheets through GDAL: CSV, xlsx, ods (and xls when the driver is present)."""

import pytest

from engine.tables import (
    TableError, parameter_sheet, parameter_values, read_table, sheets, write_table, number,
)

VALUES = {"Rural": 2500.0, "Urbain1": {"2025": 10000.0, "2040": 12000.0}, "*": 2500.0}


@pytest.mark.parametrize("extension", [".csv", ".xlsx", ".ods"])
def test_parameter_table_round_trip(tmp_path, extension):
    path = str(tmp_path / f"dmax{extension}")
    write_table(path, *parameter_sheet(VALUES))
    table = read_table(path)
    assert table.headers[:2] == ["zone", "constant"]
    assert parameter_values(table) == VALUES


def test_crossed_parameter_table(tmp_path):
    values = {"A|Urbain1": 4.0, "A|*": {"2025": 2.0, "2035": 1.5}, "*|Rural": 1.0, "*": 2.2}
    headers, rows = parameter_sheet(values, crossed=True)
    assert headers[:3] == ["zone", "zone_2", "constant"]
    path = str(tmp_path / "tcam.xlsx")
    write_table(path, headers, rows)
    assert parameter_values(read_table(path), crossed=True) == values


def test_csv_written_by_hand(tmp_path):
    path = tmp_path / "tcam.csv"
    path.write_text("Zone;Constante;2025;2040\nMURAMVYA RURAL;;2,2;1,9\nMURAMVYA URBAIN;3,5;;\n;2,0;;\n",
                    encoding="cp1252")
    values = parameter_values(read_table(str(path)))
    assert values == {"MURAMVYA RURAL": {"2025": 2.2, "2040": 1.9}, "MURAMVYA URBAIN": 3.5, "*": 2.0}


def test_sheets_and_errors(tmp_path):
    path = str(tmp_path / "t.xlsx")
    write_table(path, ["a", "b"], [["x", 1.0]])
    assert sheets(path) == ["parameters"]
    with pytest.raises(TableError):
        read_table(path, sheet="absent")
    with pytest.raises(TableError):
        read_table(str(tmp_path / "t.docx"))
    assert number("2 500,5") == 2500.5 and number("") is None



def test_projections_long_and_wide(tmp_path):
    from engine.tables import LONG, WIDE, read_projections

    long = tmp_path / "long.csv"
    long.write_text("Commune;Année;Population\nA;2026;800\nA;2030;1000\nB;2026;600\n", encoding="utf-8")
    table = read_projections(str(long))
    assert table.layout == LONG and table.unit_column == "Commune"
    assert table.series == {"A": [(2026, 800), (2030, 1000)], "B": [(2026, 600)]}

    wide = str(tmp_path / "wide.xlsx")
    write_table(wide, ["Code", "Commune", "2026", "2030"], [[101.0, "A", 800.0, 1000.0], [102.0, "B", 600.0, 700.0]])
    table = read_projections(wide, unit_column="Commune")
    assert table.layout == WIDE and table.series["B"] == [(2026, 600), (2030, 700)] and table.years() == [2026, 2030]
    assert set(read_projections(wide).series) == {"A", "B"}      # « Commune » is recognised as the unit column
    coded = str(tmp_path / "coded.xlsx")
    write_table(coded, ["Code", "Libellé", "2026"], [[101.0, "A", 800.0], [102.0, "B", 600.0]])
    assert set(read_projections(coded).series) == {"101", "102"}  # numeric codes read as the layer shows them

    with pytest.raises(TableError):
        read_projections(str(long), year_column="absent")

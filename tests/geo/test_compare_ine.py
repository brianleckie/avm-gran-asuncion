import csv
import zipfile

from compare_ine import compare


def test_column_positions_and_leading_zeros(tmp_path):
    source = tmp_path / "source.xlsx"
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    strings = ["11", "CENTRAL", "09", "LUQUE", "015", "MARAMBURE"]
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<sst xmlns="{ns}">' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            f'<worksheet xmlns="{ns}"><sheetData>'
            '<row r="4">'
            + "".join(f'<c r="{col}4" t="s"><v>{i}</v></c>' for i, col in enumerate("BCDEFG"))
            + "</row></sheetData></worksheet>",
        )
    gazetteer = tmp_path / "gazetteer.csv"
    gazetteer.write_text("city,aliases\nluque,marambure\n", encoding="utf-8")
    compare(source, gazetteer, tmp_path)
    with (tmp_path / "ine_comparison.csv").open(encoding="utf-8", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert (row["ine_department"], row["ine_district"], row["ine_locality"]) == ("11", "09", "015")
    assert row["status"] == "exact_name_or_alias"

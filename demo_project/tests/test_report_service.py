from app.services.report_service import export_report


def test_export_report_normal_data():
    result = export_report([{"name": "Tuan"}])
    assert result == "Exported 1 rows"


def test_export_report_empty_data():
    result = export_report([])
    assert result == "No data to export"


def test_export_report_none_data():
    result = export_report(None)
    assert result == "No data to export"
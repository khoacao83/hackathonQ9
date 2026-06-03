from __future__ import annotations

from typing import Any

from app.utils.excel_helper import export_excel


def export_report(data: list[dict[str, Any]] | None) -> str:
    """
    Bug demo:
    - [] nên trả về "No data to export"
    - None nên trả về "No data to export"
    - hiện tại chưa xử lý gì, cứ gọi export_excel
    """
    return export_excel(data)
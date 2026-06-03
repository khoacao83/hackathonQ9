from __future__ import annotations

from collections.abc import Sized
from typing import Any


def export_excel(data: Sized) -> str:
    """
    Demo helper giả lập export Excel.

    Hàm này cố tình đơn giản để test lỗi nằm ở report_service:
    - Nếu data là None, len(data) sẽ lỗi.
    - report_service cần xử lý None trước khi gọi helper.
    """
    return f"Exported {len(data)} rows"

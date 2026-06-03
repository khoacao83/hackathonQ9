from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MockLLMClient:
    """
    Mock AI client dùng để demo self-healing.

    Attempt 1:
        Chỉ fix [].
        None vẫn fail.

    Attempt 2:
        Fix cả None và [].
    """

    def generate_patch(
        self,
        task: str,
        context: str,
        error_summary: list[str] | None = None,
    ) -> str:
        if error_summary:
            return self._generate_fixed_patch(task, error_summary)

        return self._generate_first_patch(task)

    def _generate_first_patch(self, task: str) -> str:
        return """--- a/app/services/report_service.py
+++ b/app/services/report_service.py
@@ -8,8 +8,5 @@
-def export_report(data: list[dict[str, Any]] | None) -> str:
-    \"\"\"
-    Bug demo:
-    - [] nên trả về \"No data to export\"
-    - None nên trả về \"No data to export\"
-    - hiện tại chưa xử lý gì, cứ gọi export_excel
-    \"\"\"
-    return export_excel(data)
+def export_report(data: list[dict[str, Any]] | None) -> str:
+    if len(data) == 0:
+        return "No data to export"
+
+    return export_excel(data)
"""

    def _generate_fixed_patch(
        self,
        task: str,
        error_summary: list[str],
    ) -> str:
        return """--- a/app/services/report_service.py
+++ b/app/services/report_service.py
@@ -8,5 +8,5 @@
 def export_report(data: list[dict[str, Any]] | None) -> str:
-    if len(data) == 0:
+    if data is None or len(data) == 0:
         return "No data to export"
 
     return export_excel(data)
"""
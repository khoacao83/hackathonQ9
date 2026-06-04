# Mock LLM client — no API key needed, fully deterministic for demo.
#
# Dispatch by target_file:
#   banking/payment_service.py → _BANKING_PATCH_*
#   inventory/*               → _INVENTORY_PATCH_*

# ── Banking patches ─────────────────────────────────────────────────────────
# Attempt 1: checks amount and fee separately (still wrong for edge case)
# Attempt 2: correct check amount + fee together
_BANKING_PATCH_1 = '''\
--- a/app/banking/payment_service.py
+++ b/app/banking/payment_service.py
@@ -18,7 +18,7 @@
         fee = calculate_transfer_fee(amount)
         sender_balance = self.store.get_balance(from_account)
 
-        if sender_balance < amount:
+        if sender_balance < amount or sender_balance < fee:
             return {
                 "status": "declined",
                 "reason": "Insufficient funds",
'''

_BANKING_PATCH_2 = '''\
--- a/app/banking/payment_service.py
+++ b/app/banking/payment_service.py
@@ -18,7 +18,7 @@
         fee = calculate_transfer_fee(amount)
         sender_balance = self.store.get_balance(from_account)
 
-        if sender_balance < amount:
+        if sender_balance < amount + fee:
             return {
                 "status": "declined",
                 "reason": "Insufficient funds",
'''

# ── Inventory patches ────────────────────────────────────────────────────────
# Attempt 1: only fixes inventory_store.get_available — misses order_service
#            and reservation_service bugs → some tests still fail
# Attempt 2: fixes all 3 files (inventory_store + reservation_service + order_service)
_INVENTORY_PATCH_1 = '''\
--- a/app/inventory/inventory_store.py
+++ b/app/inventory/inventory_store.py
@@ fix get_available to subtract reserved @@
FIX:inventory_store_only
'''

_INVENTORY_PATCH_2 = '''\
--- a/app/inventory/inventory_store.py
+++ b/app/inventory/inventory_store.py
--- a/app/inventory/reservation_service.py
+++ b/app/inventory/reservation_service.py
--- a/app/inventory/order_service.py
+++ b/app/inventory/order_service.py
@@ fix all inventory bugs @@
FIX:inventory_all
'''


def _build_prompt(
    task: str,
    target_file: str,
    related_files: list[str],
    optimized_context: str,
    error_summary: str,
    objective: str,
) -> str:
    """Build the unified structured prompt as defined in the team prompt format."""
    return f"""SYSTEM ROLE:
You are an AI Code Assembly Line component.
You must prioritize safety, minimal change, testability, and auditability.

OBJECTIVE:
{objective}

INPUT:
- User task: {task}
- Target file: {target_file}
- Related files: {related_files}
- Optimized context:
{optimized_context}

CONSTRAINTS:
1. Do not modify unrelated files.
2. Do not invent requirements.
3. Prefer minimal patch.
4. Preserve existing public API unless required.
5. Generated code must pass existing tests.
6. If test error is provided, fix only that error.
7. Output must be machine-readable.

ERROR SUMMARY IF ANY:
{error_summary}

EXPECTED OUTPUT:
Return only unified diff."""


def generate_patch(
    task: str,
    context: str,
    attempt: int = 1,
    error_feedback: str = "",
    target_file: str = "",
    related_files: list[str] | None = None,
) -> str:
    """
    Simulate an LLM generating a patch.

    Builds the structured prompt (logged for transparency), then returns
    a deterministic response:
      attempt=1 → buggy patch (only handles `== []`, misses None)
      attempt>=2 → correct patch (uses `not data`, handles both None and [])
    """
    objective = (
        "Fix the failing behavior identified in the error summary."
        if error_feedback
        else "Generate a minimal patch to satisfy the user task."
    )
    # Build structured prompt (mirrors real LLM usage — mock ignores it)
    _prompt = _build_prompt(
        task=task,
        target_file=target_file,
        related_files=related_files or [],
        optimized_context=context,
        error_summary=error_feedback,
        objective=objective,
    )
    # Deterministic mock response — real LLM would process _prompt here
    # Dispatch by target domain
    if "inventory" in target_file:
        if attempt == 1:
            return _INVENTORY_PATCH_1
        return _INVENTORY_PATCH_2
    else:
        if attempt == 1:
            return _BANKING_PATCH_1
        return _BANKING_PATCH_2

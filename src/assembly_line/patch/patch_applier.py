"""
Applies the mock LLM patch to the sandbox copy of the target file(s).

Dispatches by target domain (banking / inventory). Rather than parsing
unified diff, we directly write the known fixed content so the demo
works reliably cross-platform.
"""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


# ── Inventory fixed content ────────────────────────────────────────────────

_INVENTORY_STORE_FIXED = '''\
class InventoryStore:
    def __init__(self):
        self.products = {}

    def add_product(self, product_id: str, quantity: int):
        self.products[product_id] = {
            "stock": quantity,
            "reserved": 0,
        }

    def get_stock(self, product_id: str) -> int:
        return self.products[product_id]["stock"]

    def get_reserved(self, product_id: str) -> int:
        return self.products[product_id]["reserved"]

    def get_available(self, product_id: str) -> int:
        product = self.products[product_id]
        return product["stock"] - product["reserved"]

    def increase_reserved(self, product_id: str, quantity: int):
        self.products[product_id]["reserved"] += quantity

    def decrease_reserved(self, product_id: str, quantity: int):
        self.products[product_id]["reserved"] -= quantity

    def decrease_stock(self, product_id: str, quantity: int):
        self.products[product_id]["stock"] -= quantity
'''

_RESERVATION_SERVICE_FIXED = '''\
class ReservationService:
    def __init__(self, inventory_store):
        self.inventory_store = inventory_store

    def reserve(self, product_id: str, quantity: int):
        available = self.inventory_store.get_available(product_id)

        if available < quantity:
            return {
                "status": "failed",
                "reason": "Insufficient inventory",
            }

        self.inventory_store.increase_reserved(product_id, quantity)

        return {
            "status": "reserved",
            "product_id": product_id,
            "quantity": quantity,
        }

    def release(self, product_id: str, quantity: int):
        current = self.inventory_store.get_reserved(product_id)
        actual = min(quantity, current)
        if actual > 0:
            self.inventory_store.decrease_reserved(product_id, actual)

        return {
            "status": "released",
            "product_id": product_id,
            "quantity": actual,
        }

    def commit(self, product_id: str, quantity: int):
        self.inventory_store.decrease_stock(product_id, quantity)
        self.inventory_store.decrease_reserved(product_id, quantity)

        return {
            "status": "committed",
            "product_id": product_id,
            "quantity": quantity,
        }
'''

_ORDER_SERVICE_FIXED = '''\
class OrderService:
    def __init__(self, reservation_service, payment_gateway):
        self.reservation_service = reservation_service
        self.payment_gateway = payment_gateway

    def place_order(self, customer_id: str, product_id: str, quantity: int, unit_price: int):
        reservation = self.reservation_service.reserve(product_id, quantity)

        if reservation["status"] != "reserved":
            return {
                "status": "declined",
                "reason": reservation["reason"],
            }

        payment = self.payment_gateway.charge(
            customer_id=customer_id,
            amount=quantity * unit_price,
        )

        if payment["status"] != "paid":
            self.reservation_service.release(product_id, quantity)
            return {
                "status": "declined",
                "reason": "Payment failed",
            }

        commit = self.reservation_service.commit(product_id, quantity)

        return {
            "status": "confirmed",
            "reservation": reservation,
            "payment": payment,
            "commit": commit,
        }
'''


def _apply_inventory_partial(project_root: str) -> list[str]:
    """Attempt 1: only fix inventory_store (still missing reservation/order fixes)."""
    base = Path(project_root) / "app" / "inventory"
    store = base / "inventory_store.py"
    store.write_text(_INVENTORY_STORE_FIXED, encoding="utf-8")
    return [str(store)]


def _apply_inventory_full(project_root: str) -> list[str]:
    """Attempt 2+: fix all 3 inventory files."""
    base = Path(project_root) / "app" / "inventory"
    files = [
        (base / "inventory_store.py", _INVENTORY_STORE_FIXED),
        (base / "reservation_service.py", _RESERVATION_SERVICE_FIXED),
        (base / "order_service.py", _ORDER_SERVICE_FIXED),
    ]
    changed = []
    for path, content in files:
        path.write_text(content, encoding="utf-8")
        changed.append(str(path))
    return changed

# Attempt 1 — buggy fix: checks amount and fee separately, still fails
# when balance == amount (e.g. 100.0 balance, 100.0 transfer + 1.0 fee)
_FIXED_V1 = '''\
from app.banking.account_store import AccountStore
from app.banking.fee_calculator import calculate_transfer_fee


class PaymentService:
    def __init__(self, store: AccountStore):
        self.store = store

    def transfer(self, from_account: str, to_account: str, amount: float) -> dict:
        if from_account == to_account:
            return {
                "status": "declined",
                "reason": "Cannot transfer to the same account",
            }

        fee = calculate_transfer_fee(amount)
        sender_balance = self.store.get_balance(from_account)

        if sender_balance < amount or sender_balance < fee:
            return {
                "status": "declined",
                "reason": "Insufficient funds",
            }

        self.store.debit(from_account, amount + fee)
        self.store.credit(to_account, amount)

        return {
            "status": "success",
            "amount": amount,
            "fee": fee,
            "total_debited": amount + fee,
        }
'''

# Attempt 2+ — correct fix: checks balance covers full amount + fee
_FIXED_V2 = '''\
from app.banking.account_store import AccountStore
from app.banking.fee_calculator import calculate_transfer_fee


class PaymentService:
    def __init__(self, store: AccountStore):
        self.store = store

    def transfer(self, from_account: str, to_account: str, amount: float) -> dict:
        if from_account == to_account:
            return {
                "status": "declined",
                "reason": "Cannot transfer to the same account",
            }

        fee = calculate_transfer_fee(amount)
        sender_balance = self.store.get_balance(from_account)

        if sender_balance < amount + fee:
            return {
                "status": "declined",
                "reason": "Insufficient funds",
            }

        self.store.debit(from_account, amount + fee)
        self.store.credit(to_account, amount)

        return {
            "status": "success",
            "amount": amount,
            "fee": fee,
            "total_debited": amount + fee,
        }
'''


def apply_demo_patch(
    project_root: str,
    patch_text: str,
    allowed_files: list[str] | None = None,
) -> list[str]:
    """
    Apply a demo patch to the sandbox.

    Dispatches to the correct domain handler based on patch content,
    writes the fixed file(s), and returns a list of changed file paths.
    """
    if "inventory" in patch_text:
        if "inventory_all" in patch_text:
            return _apply_inventory_full(project_root)
        else:
            return _apply_inventory_partial(project_root)

    target = Path(project_root) / "app" / "banking" / "payment_service.py"
    # Keep deterministic banking behavior for the demo project only.
    if target.exists() and ("amount + fee" in patch_text or "sender_balance < amount" in patch_text):
        new_content = _FIXED_V2 if "amount + fee" in patch_text else _FIXED_V1
        target.write_text(new_content, encoding="utf-8")
        return [str(target)]

    allowed_set = {
        _normalize_rel_path(p).replace("\\", "/")
        for p in (allowed_files or [])
        if p and p.strip()
    }

    changed_paths = []
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            candidate = _normalize_rel_path(line[len("+++ "):].strip()).replace("\\", "/")
            if candidate and candidate != "/dev/null":
                changed_paths.append(candidate)

    # Generic path: apply unified diff directly in sandbox for non-demo projects.
    fallback_error = None
    if _git_available():
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".diff", delete=False) as tmp:
            tmp.write(patch_text)
            tmp_path = tmp.name

        try:
            result = subprocess.run(
                ["git", "apply", "--whitespace=nowarn", "--recount", "-p1", tmp_path],
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)

        if result.returncode != 0:
            fallback_error = (result.stderr or result.stdout or "unknown error").strip()
    else:
        fallback_error = "git executable not found"

    if fallback_error:
        _apply_unified_diff_python(project_root, patch_text, allowed_set)

    if changed_paths:
        if allowed_set:
            changed_paths = [p for p in changed_paths if p in allowed_set]
        return [str(Path(project_root) / rel) for rel in dict.fromkeys(changed_paths)]

    # Fallback when diff has no standard +++ headers.
    return []


def _git_available() -> bool:
    return shutil.which("git") is not None


def _normalize_rel_path(path_value: str) -> str:
    rel = path_value.strip()
    if rel.startswith("a/") or rel.startswith("b/"):
        rel = rel[2:]
    return rel


def _parse_unified_diff(patch_text: str) -> list[tuple[str, list[tuple[int, int, int, int, list[str]]]]]:
    lines = patch_text.splitlines()
    i = 0
    parsed: list[tuple[str, list[tuple[int, int, int, int, list[str]]]]] = []

    while i < len(lines):
        if not lines[i].startswith("--- "):
            i += 1
            continue

        if i + 1 >= len(lines) or not lines[i + 1].startswith("+++ "):
            i += 1
            continue

        new_path = _normalize_rel_path(lines[i + 1][4:])
        i += 2
        hunks: list[tuple[int, int, int, int, list[str]]] = []

        while i < len(lines) and not lines[i].startswith("--- "):
            if not lines[i].startswith("@@ "):
                i += 1
                continue

            match = re.match(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@", lines[i])
            if not match:
                i += 1
                continue

            old_start = int(match.group(1))
            old_count = int(match.group(2) or "1")
            new_start = int(match.group(3))
            new_count = int(match.group(4) or "1")
            i += 1

            hunk_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("@@ ") and not lines[i].startswith("--- "):
                if lines[i].startswith("\\ No newline at end of file"):
                    i += 1
                    continue
                hunk_lines.append(lines[i])
                i += 1

            hunks.append((old_start, old_count, new_start, new_count, hunk_lines))

        if new_path and hunks:
            parsed.append((new_path, hunks))

    return parsed


def _apply_hunks_to_lines(file_lines: list[str], hunks: list[tuple[int, int, int, int, list[str]]]) -> list[str]:
    def _line_eq(actual: str, expected: str) -> bool:
        return actual.rstrip("\r\n") == expected.rstrip("\r\n")

    def _find_anchor(start_index: int, anchor: str) -> int:
        # Search near expected position to tolerate small line-number drift.
        lo = max(0, start_index - 200)
        hi = min(len(result), start_index + 201)
        for idx in range(lo, hi):
            if _line_eq(result[idx], anchor):
                return idx
        return -1

    def _find_forward(cursor: int, expected: str) -> int:
        # Fuzzy forward scan used when a hunk misses newly inserted lines
        # (for example explanatory comments between function header and return).
        hi = min(len(result), cursor + 40)
        for idx in range(cursor + 1, hi):
            if _line_eq(result[idx], expected):
                return idx
        return -1

    result = list(file_lines)
    offset = 0

    for old_start, _old_count, _new_start, _new_count, hunk_lines in hunks:
        index = old_start - 1 + offset
        if index < 0:
            index = 0
        if index > len(result):
            index = len(result)

        # Use first context/delete line as anchor if available.
        anchor = None
        for hline in hunk_lines:
            if hline[:1] in {" ", "-"}:
                anchor = hline[1:]
                break
        if anchor is not None:
            needs_relocate = index >= len(result) or not _line_eq(result[index], anchor)
            if needs_relocate:
                relocated = _find_anchor(index, anchor)
                if relocated != -1:
                    index = relocated

        cursor = index
        replacement: list[str] = []

        for hline in hunk_lines:
            prefix = hline[:1]
            content = hline[1:]

            if prefix == " ":
                if cursor >= len(result) or not _line_eq(result[cursor], content):
                    found = -1 if cursor >= len(result) else _find_forward(cursor, content)
                    if found == -1:
                        raise RuntimeError("Context mismatch while applying unified diff")
                    # Preserve skipped lines unchanged and realign cursor.
                    while cursor < found:
                        replacement.append(result[cursor])
                        cursor += 1
                replacement.append(result[cursor])
                cursor += 1
            elif prefix == "-":
                if cursor >= len(result) or not _line_eq(result[cursor], content):
                    found = -1 if cursor >= len(result) else _find_forward(cursor, content)
                    if found == -1:
                        # Be tolerant when the to-be-deleted line is not found.
                        # This can happen when model output is approximate or the
                        # change is already partially applied. Keep going so the
                        # corresponding '+' lines can still land.
                        continue
                    # Keep inserted lines and delete the matched target line.
                    while cursor < found:
                        replacement.append(result[cursor])
                        cursor += 1
                cursor += 1
            elif prefix == "+":
                replacement.append(content + "\n")

        result[index:cursor] = replacement
        offset += len(replacement) - (cursor - index)

    return result


def _apply_unified_diff_python(project_root: str, patch_text: str, allowed_set: set[str] | None = None) -> None:
    parsed = _parse_unified_diff(patch_text)
    if not parsed:
        raise RuntimeError("Failed to apply unified diff: unsupported or empty diff format")

    applied_any = False
    missing_targets: list[str] = []

    normalized_allowed = {p.replace("\\", "/") for p in (allowed_set or set())}

    for rel_path, hunks in parsed:
        rel_norm = rel_path.replace("\\", "/")
        if normalized_allowed and rel_norm not in normalized_allowed:
            continue
        file_path = Path(project_root) / rel_path
        if not file_path.exists():
            missing_targets.append(rel_path)
            continue

        original = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        updated = _apply_hunks_to_lines(original, hunks)
        file_path.write_text("".join(updated), encoding="utf-8")
        applied_any = True

    if not applied_any:
        if missing_targets:
            raise RuntimeError(
                f"Failed to apply unified diff: target file not found: {missing_targets[0]}"
            )
        raise RuntimeError("Failed to apply unified diff: no applicable hunks")

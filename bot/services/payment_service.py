"""Business logic for manual USDC-on-Base premium payments (no on-chain verification)."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from bot.database.db import (
    get_payment_by_id,
    get_user_premium_status_fresh,
    set_user_premium,
    update_payment_from_pending,
)

logger = logging.getLogger(__name__)

# Plan keys stored in DB / FSM (lowercase)
PLAN_MONTHLY = "monthly"
PLAN_YEARLY = "yearly"
PLAN_LIFETIME = "lifetime"

PLAN_AMOUNTS_USD: dict[str, float] = {
    PLAN_MONTHLY: 6.0,
    PLAN_YEARLY: 49.0,
    PLAN_LIFETIME: 79.0,
}

PLAN_LABEL: dict[str, str] = {
    PLAN_MONTHLY: "Monthly",
    PLAN_YEARLY: "Yearly",
    PLAN_LIFETIME: "Lifetime",
}


def amount_for_plan(plan: str) -> Optional[float]:
    return PLAN_AMOUNTS_USD.get(plan)


def normalize_plan(callback_data: str) -> Optional[str]:
    if callback_data.endswith(PLAN_MONTHLY):
        return PLAN_MONTHLY
    if callback_data.endswith(PLAN_YEARLY):
        return PLAN_YEARLY
    if callback_data.endswith(PLAN_LIFETIME):
        return PLAN_LIFETIME
    return None


_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


def normalize_tx_hash(raw: str) -> tuple[Optional[str], Optional[str]]:
    """
    Normalize EVM tx hash. Returns (normalized_hash, error_message).
    """
    s = (raw or "").strip()
    if not s:
        return None, "Transaction hash cannot be empty."
    if s.startswith("0x") or s.startswith("0X"):
        body = s[2:]
    else:
        body = s
    if not _HEX64.match(body):
        return None, "Invalid transaction hash format. Use a Base network TXID (0x + 64 hex characters)."
    return "0x" + body.lower(), None


async def activate_premium_for_approved_plan(user_id: int, plan: str) -> None:
    """
    Apply purchased premium for an approved payment. Extends from current purchased expiry if still active.
    """
    status = await get_user_premium_status_fresh(user_id)
    now = datetime.utcnow()
    base = now
    premium_expires_at = status.get("premium_expires_at")
    purchased_active = bool(status.get("purchased_active"))
    if purchased_active and premium_expires_at:
        try:
            exp = datetime.fromisoformat(str(premium_expires_at).replace("Z", ""))
            if exp > now:
                base = exp
        except Exception:
            pass

    if plan == PLAN_MONTHLY:
        new_exp = base + timedelta(days=30)
    elif plan == PLAN_YEARLY:
        new_exp = base + timedelta(days=365)
    elif plan == PLAN_LIFETIME:
        new_exp = base + timedelta(days=365 * 100)
    else:
        new_exp = base + timedelta(days=30)

    label = PLAN_LABEL.get(plan, "Premium")
    await set_user_premium(
        user_id,
        True,
        plan=label,
        next_billing=None,
        plan_type=plan,
        premium_expires_at=new_exp.isoformat(),
    )


async def approve_payment(payment_id: int) -> tuple[bool, Optional[dict]]:
    """
    Mark payment approved and activate premium. Returns (ok, payment_row_or_none).
    """
    row = await get_payment_by_id(payment_id)
    if not row or row["status"] != "pending":
        return False, row

    plan = str(row["plan"]).strip().lower()
    if plan not in PLAN_AMOUNTS_USD:
        logger.error("approve_payment: unknown plan %r for payment %s", plan, payment_id)
        return False, row

    ok = await update_payment_from_pending(payment_id, "approved")
    if not ok:
        logger.warning("approve_payment: could not transition payment %s from pending", payment_id)
        return False, await get_payment_by_id(payment_id)

    uid = int(row["user_id"])
    try:
        await activate_premium_for_approved_plan(uid, plan)
    except Exception:
        logger.exception("activate_premium_for_approved_plan failed payment_id=%s user=%s", payment_id, uid)
    logger.info("Payment %s approved; premium activated for user %s plan=%s", payment_id, uid, plan)
    return True, await get_payment_by_id(payment_id)


async def reject_payment(payment_id: int) -> tuple[bool, Optional[dict]]:
    row = await get_payment_by_id(payment_id)
    if not row or row["status"] != "pending":
        return False, row

    ok = await update_payment_from_pending(payment_id, "rejected")
    if ok:
        logger.info("Payment %s rejected for user %s", payment_id, row["user_id"])
    return ok, await get_payment_by_id(payment_id)

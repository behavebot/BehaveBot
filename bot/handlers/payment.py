"""Manual USDC (Base) premium payments: user flow + admin approval."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS, PAYMENT_BASE_USDC_WALLET
from bot.database.db import (
    get_pending_payments,
    insert_payment_pending,
    user_has_pending_payment,
    payment_tx_hash_exists,
)
from bot.keyboards.inline import (
    kb_payment_rejected_followup,
    kb_premium_payment_plans,
    kb_premium_landing,
    kb_payment_plan_back_only,
)
from bot.services import payment_service as pay
from bot.states import PaymentStates

logger = logging.getLogger(__name__)

router = Router(name="payment")

MSG_PENDING_EXISTS = "You already have a pending payment under review."

def build_submit_success_text(plan_key: str) -> str:
    plan_disp = _plan_label_with_price(plan_key)
    return (
        "━━━━━━━━━━\n\n"
        "<b>✅ Payment Submitted</b>\n\n"
        "Your transaction has been received and is under review.\n\n"
        f"<b>Plan:</b> {plan_disp}\n\n"
        "<b>Status:</b> Pending approval\n\n"
        "You will be notified once approved.\n\n"
        "━━━━━━━━━━"
    )

USER_MSG_APPROVED = (
    "Payment confirmed.\n"
    "Your premium access is now active."
)

PAYMENT_REJECTED_USER_HTML = (
    "❌ <b>Payment Rejected</b>\n\n"
    "Your payment could not be verified.\n\n"
    "If you believe this is a mistake, please contact support."
)

ADMIN_MANUAL_VERIFY_WARNING = (
    "⚠️ Manual verification required (amount not verified on-chain)"
)


def _plan_label_with_price(plan_key: str) -> str:
    pk = (plan_key or "").strip().lower()
    label = pay.PLAN_LABEL.get(pk, plan_key or "—")
    amt = pay.amount_for_plan(pk)
    if amt is not None:
        return f"{label} (${amt:.0f})"
    return label


def _parse_created_at(created_at: str) -> datetime | None:
    raw = (created_at or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _relative_submitted(created_at: str) -> str:
    dt = _parse_created_at(created_at)
    if dt is None:
        return "unknown time"
    now = datetime.now(dt.tzinfo or timezone.utc)
    delta = now - dt
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return f"{secs} sec ago"
    if secs < 3600:
        m = secs // 60
        return f"{m} min ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hr ago"
    d = secs // 86400
    return f"{d} day(s) ago"


async def _username_or_dash(bot, uid: int) -> str:
    try:
        chat = await bot.get_chat(uid)
        u = getattr(chat, "username", None)
        if u:
            return f"@{u}"
    except Exception:
        pass
    return "—"


def build_payment_plan_picker_text() -> str:
    """Step 0 — choose plan only (wallet shown after selection)."""
    return (
        "🚀 <b>BehaveBot Premium Access</b>\n\n"
        "Choose a plan:\n\n"
        "💳 Monthly — $6\n"
        "💳 Yearly — $49\n"
        "💳 Lifetime — $79"
    )


def _wallet_copy_block_html(wallet: str) -> str:
    """Single-line address in &lt;code&gt; for tap-to-copy; wallet from config only."""
    w = (wallet or "").strip()
    return f"<code>{w}</code>\n(Tap to copy)"


def build_plan_selected_text(wallet: str, plan_key: str) -> str:
    """Step 1 — wallet + instructions; user replies with TX hash in chat."""
    plan_disp = _plan_label_with_price(plan_key)
    wallet_block = _wallet_copy_block_html(wallet)
    return (
        "━━━━━━━━━━\n\n"
        "💳 <b>Premium Plan Selected</b>\n\n"
        f"<b>Plan:</b> {plan_disp}\n\n"
        "<b>Payment Method:</b> USDC (Base)\n\n"
        "Send <b>EXACT</b> amount to:\n\n"
        f"{wallet_block}\n\n"
        "━━━━━━━━━━\n\n"
        "⚠️ <b>Important:</b>\n"
        "• Use Base network only\n"
        "• Send exact amount\n"
        "• Wrong network = funds lost\n\n"
        "━━━━━━━━━━\n\n"
        "After sending, reply with your TX hash."
    )


async def show_premium_payment_screen(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        build_payment_plan_picker_text(),
        reply_markup=kb_premium_payment_plans(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay_sel_"))
async def pay_select_plan(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    plan = pay.normalize_plan(callback.data or "")
    if not plan:
        return
    amt = pay.amount_for_plan(plan)
    await state.update_data(payment_plan=plan, payment_amount_usd=amt)
    await state.set_state(PaymentStates.waiting_tx_hash)
    text = build_plan_selected_text(PAYMENT_BASE_USDC_WALLET, plan)
    await callback.message.edit_text(text, reply_markup=kb_payment_plan_back_only(), parse_mode="HTML")


@router.callback_query(F.data == "payment_back_plan_select")
async def payment_back_plan_select(callback: CallbackQuery, state: FSMContext) -> None:
    """Back from step 1 → step 0 (plan picker)."""
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        build_payment_plan_picker_text(),
        reply_markup=kb_premium_payment_plans(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "payment_back_premium")
async def payment_back_premium(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    from bot.handlers.premium import _build_premium_message

    text = await _build_premium_message(callback.from_user.id)
    await callback.message.edit_text(text, reply_markup=kb_premium_landing())


@router.message(Command("cancel"), StateFilter(PaymentStates.waiting_tx_hash))
async def pay_cancel_tx(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Payment submission cancelled. Open Premium again when you’re ready.")


@router.message(StateFilter(PaymentStates.waiting_tx_hash), F.text)
async def pay_receive_tx_hash(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id
    data = await state.get_data()
    plan = data.get("payment_plan")
    if not plan:
        await state.clear()
        await message.answer("Session expired. Please start again from Unlock Premium.")
        return

    expected = pay.amount_for_plan(plan)
    if expected is None:
        await state.clear()
        await message.answer("Invalid plan. Please start again from Unlock Premium.")
        return

    # Single pending payment per user (before TX parsing — clear UX and avoids wasted validation).
    if await user_has_pending_payment(uid):
        await state.clear()
        await message.answer(MSG_PENDING_EXISTS)
        return

    raw = (message.text or "").strip()
    try:
        tx_hash, err = pay.normalize_tx_hash(raw)
    except Exception:
        logger.exception("normalize_tx_hash failed for user %s", uid)
        await message.answer(
            "Invalid transaction hash format. Please send a valid Base TX hash (0x + 64 hex characters)."
        )
        return
    if err:
        await message.answer(err)
        return

    if await payment_tx_hash_exists(tx_hash):
        await message.answer("This transaction hash was already submitted. Use a different TX or contact support.")
        return

    try:
        pid = await insert_payment_pending(uid, plan, float(expected), tx_hash)
    except Exception:
        logger.exception("insert_payment_pending failed for user %s", uid)
        await message.answer("Could not save your payment. Please try again in a moment or contact support.")
        return

    if pid is None:
        await message.answer("This transaction hash is already registered. If you believe this is an error, contact support.")
        return

    await state.clear()
    await message.answer(build_submit_success_text(plan), parse_mode="HTML")


def _admin_kb(payment_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"pay_adm_ok:{payment_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"pay_adm_no:{payment_id}"),
            ]
        ]
    )


async def _build_admin_payment_text(bot, r: dict) -> str:
    uid = int(r["user_id"])
    uname = await _username_or_dash(bot, uid)
    plan_disp = _plan_label_with_price(str(r["plan"]))
    rel = _relative_submitted(str(r.get("created_at") or ""))
    tx = str(r.get("tx_hash") or "")
    return (
        f"<b>Username:</b> {uname}\n"
        f"<b>User ID:</b> <code>{uid}</code>\n"
        f"<b>Plan:</b> {plan_disp}\n"
        f"<b>Submitted:</b> {rel}\n"
        f"<b>TX:</b> <code>{tx}</code>"
    )


async def _send_admin_payments_list(bot, chat_id: int) -> None:
    rows = await get_pending_payments()
    if not rows:
        await bot.send_message(chat_id, "💰 <b>Pending Payments</b>\n\nNo pending payments.", parse_mode="HTML")
        return
    await bot.send_message(
        chat_id,
        "💰 <b>Pending Payments</b>\n\n"
        f"{ADMIN_MANUAL_VERIFY_WARNING}\n\n"
        "Review each entry below.",
        parse_mode="HTML",
    )
    for r in rows:
        txt = await _build_admin_payment_text(bot, r)
        await bot.send_message(chat_id, txt, reply_markup=_admin_kb(int(r["id"])), parse_mode="HTML")


@router.callback_query(F.data == "admin_payments")
async def admin_payments_cb(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    await callback.answer()
    await _send_admin_payments_list(callback.bot, callback.message.chat.id)


@router.callback_query(F.data.startswith("pay_adm_ok:"))
async def admin_approve_payment(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    try:
        pid = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Invalid.", show_alert=True)
        return
    ok, row = await pay.approve_payment(pid)
    if not ok or not row:
        await callback.answer("Could not approve (already processed or missing).", show_alert=True)
        return
    await callback.answer("Approved")
    try:
        base = callback.message.text or ""
        await callback.message.edit_text(base + "\n\n✅ APPROVED by admin")
    except Exception:
        pass
    uid = int(row["user_id"])
    try:
        await callback.bot.send_message(uid, USER_MSG_APPROVED)
    except Exception as e:
        logger.warning("Could not notify user %s after approve: %s", uid, e)


@router.callback_query(F.data.startswith("pay_adm_no:"))
async def admin_reject_payment(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    try:
        pid = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Invalid.", show_alert=True)
        return
    ok, row = await pay.reject_payment(pid)
    if not ok or not row:
        await callback.answer("Could not reject (already processed or missing).", show_alert=True)
        return
    await callback.answer("Rejected")
    try:
        base = callback.message.text or ""
        await callback.message.edit_text(base + "\n\n❌ REJECTED by admin")
    except Exception:
        pass
    uid = int(row["user_id"])
    try:
        await callback.bot.send_message(
            uid,
            PAYMENT_REJECTED_USER_HTML,
            parse_mode="HTML",
            reply_markup=kb_payment_rejected_followup(),
        )
    except Exception as e:
        logger.warning("Could not notify user %s after reject: %s", uid, e)

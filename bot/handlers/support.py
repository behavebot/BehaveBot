"""Contact Support: user tickets → admin review."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_IDS
from bot.database.db import close_support_ticket, get_open_support_tickets, insert_support_ticket
from bot.keyboards.inline import BACK_TO_MENU_DATA, kb_back_to_menu
from bot.states.support import SupportStates

logger = logging.getLogger(__name__)

router = Router(name="support")

SUPPORT_INTRO_TEXT = (
    "📩 <b>Contact Support</b>\n\n"
    "If you have any issue, report it below.\n\n"
    "📧 Email: <code>behavebot.ai@gmail.com</code>\n"
    "🌐 Website: https://behavebot-website.vercel.app/\n"
    "𝕏 Dev: https://x.com/MoDaoStudio\n\n"
    "━━━━━━━━━━\n\n"
    "✍️ <b>Describe your issue below</b>\n\n"
    "Tell us what happened, what you expected, and any details that can help us understand your problem.\n\n"
    "<i>(Type your message and send it here)</i>\n\n"
    "━━━━━━━━━━"
)


def kb_support_image_choice() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="📷 Yes", callback_data="support_img_yes"),
        InlineKeyboardButton(text="Skip", callback_data="support_img_skip"),
    )
    return b.as_markup()


def kb_support_confirm() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="✅ Send", callback_data="support_confirm_send"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="support_confirm_cancel"),
    )
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def _relative_time(created_at: str) -> str:
    raw = (created_at or "").strip()
    if not raw:
        return "unknown"
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(dt.tzinfo or timezone.utc)
        secs = max(0, int((now - dt).total_seconds()))
        if secs < 60:
            return f"{secs} sec ago"
        if secs < 3600:
            return f"{secs // 60} min ago"
        if secs < 86400:
            return f"{secs // 3600} hr ago"
        return f"{secs // 86400} day(s) ago"
    except Exception:
        return "unknown"


async def _username_line(bot, uid: int) -> str:
    try:
        chat = await bot.get_chat(uid)
        if getattr(chat, "username", None):
            return f"User: @{chat.username}"
    except Exception:
        pass
    return "User: —"


def _escape_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


async def _send_preview(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    text = data.get("support_text") or ""
    img = data.get("support_image_file_id")
    img_line = "Attached" if img else "None"
    body = (
        "━━━━━━━━━━\n"
        "📝 <b>Your Report</b>\n\n"
        f"<b>Text:</b>\n{_escape_html(text)}\n\n"
        f"<b>Image:</b> {img_line}\n"
        "━━━━━━━━━━\n\n"
        "Are you sure you want to send this?"
    )
    await state.set_state(SupportStates.awaiting_confirm)
    await message.answer(body, reply_markup=kb_support_confirm(), parse_mode="HTML")


@router.callback_query(F.data == "support_start")
async def support_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.answer(SUPPORT_INTRO_TEXT, reply_markup=kb_back_to_menu(), parse_mode="HTML")
    await state.set_state(SupportStates.waiting_text)


@router.message(StateFilter(SupportStates.waiting_text), F.text)
async def support_receive_text(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("Please describe your issue (non-empty text).")
        return
    await state.update_data(support_text=raw)
    await state.set_state(SupportStates.waiting_image_choice)
    await message.answer(
        "Would you like to attach an image?",
        reply_markup=kb_support_image_choice(),
    )


@router.callback_query(StateFilter(SupportStates.waiting_image_choice), F.data == "support_img_yes")
async def support_img_yes(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(SupportStates.waiting_photo)
    await callback.message.answer("📷 Please send your image now.", reply_markup=kb_back_to_menu())


@router.callback_query(StateFilter(SupportStates.waiting_image_choice), F.data == "support_img_skip")
async def support_img_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(support_image_file_id=None)
    await _send_preview(callback.message, state)


@router.message(StateFilter(SupportStates.waiting_photo), F.photo)
async def support_receive_photo(message: Message, state: FSMContext) -> None:
    fid = message.photo[-1].file_id
    await state.update_data(support_image_file_id=fid)
    await _send_preview(message, state)


@router.message(StateFilter(SupportStates.waiting_photo))
async def support_photo_expected(message: Message) -> None:
    await message.answer("Please send an image file, or tap ⬅️ Back to Menu / /cancel.")


@router.callback_query(StateFilter(SupportStates.awaiting_confirm), F.data == "support_confirm_cancel")
async def support_confirm_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("Cancelled.")


@router.callback_query(StateFilter(SupportStates.awaiting_confirm), F.data == "support_confirm_send")
async def support_confirm_send(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    text = (data.get("support_text") or "").strip()
    img = data.get("support_image_file_id")
    uid = callback.from_user.id
    if not text:
        await state.clear()
        await callback.message.answer("Nothing to send. Start again from Settings.")
        return
    try:
        await insert_support_ticket(uid, text, img)
    except Exception:
        logger.exception("insert_support_ticket failed uid=%s", uid)
        await callback.message.answer("Could not submit. Please try again later.")
        return
    await state.clear()
    await callback.message.answer(
        "✅ Your report has been submitted.\nOur team will review it shortly."
    )


def _admin_ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Resolve", callback_data=f"admin_support_resolve:{ticket_id}"),
                InlineKeyboardButton(text="❌ Ignore", callback_data=f"admin_support_ignore:{ticket_id}"),
            ]
        ]
    )


def _admin_ticket_body_html(
    uline: str, uid: int, text_body: str, rel: str, *, for_photo_caption: bool = False
) -> str:
    """Admin ticket display. No Image line. Photo captions must stay ≤1024 (trim user text)."""
    bt = (text_body or "").strip()
    max_plain = 650 if for_photo_caption else 3500
    if len(bt) > max_plain:
        bt = bt[: max_plain - 1] + "…"
    preview = _escape_html(bt)
    return (
        f"{uline}\n"
        f"<b>ID:</b> <code>{uid}</code>\n"
        f"<b>Text:</b> {preview}\n"
        f"<b>Submitted:</b> {rel}"
    )


@router.callback_query(F.data == "admin_support")
async def admin_support_list(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    await callback.answer()
    rows = await get_open_support_tickets()
    if not rows:
        await callback.message.answer("📩 <b>Report CS</b>\n\nNo open tickets.", parse_mode="HTML")
        return
    await callback.message.answer("📩 <b>Report CS</b>\n\nOpen tickets (latest first):", parse_mode="HTML")
    bot = callback.bot
    chat_id = callback.message.chat.id
    for r in rows:
        uid = int(r["user_id"])
        uline = await _username_line(bot, uid)
        rel = _relative_time(str(r.get("created_at") or ""))
        raw_text = (r.get("text") or "").strip()
        tid = int(r["id"])
        kb = _admin_ticket_kb(tid)
        img_id = r.get("image_file_id")
        if img_id:
            caption = _admin_ticket_body_html(uline, uid, raw_text, rel, for_photo_caption=True)
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=str(img_id),
                    caption=caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("send_photo for support ticket %s failed; falling back to text", tid)
                fallback = _admin_ticket_body_html(uline, uid, raw_text, rel, for_photo_caption=False)
                await bot.send_message(
                    chat_id=chat_id,
                    text=fallback + "\n\n<i>(Screenshot could not be loaded.)</i>",
                    reply_markup=kb,
                    parse_mode="HTML",
                )
        else:
            body = _admin_ticket_body_html(uline, uid, raw_text, rel, for_photo_caption=False)
            await bot.send_message(
                chat_id=chat_id,
                text=body,
                reply_markup=kb,
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("admin_support_resolve:"))
async def admin_support_resolve(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    try:
        tid = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Invalid.", show_alert=True)
        return
    ok = await close_support_ticket(tid)
    await callback.answer("Resolved" if ok else "Already closed")
    if ok:
        try:
            suffix = "\n\n✅ Resolved"
            if callback.message.photo:
                cap = (callback.message.caption or "") + suffix
                await callback.message.edit_caption(caption=cap, parse_mode="HTML")
            else:
                base = callback.message.text or ""
                await callback.message.edit_text(base + suffix, parse_mode="HTML")
        except Exception:
            pass


@router.callback_query(F.data.startswith("admin_support_ignore:"))
async def admin_support_ignore(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Access denied.", show_alert=True)
        return
    try:
        tid = int(callback.data.split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Invalid.", show_alert=True)
        return
    ok = await close_support_ticket(tid)
    await callback.answer("Ignored" if ok else "Already closed")
    if ok:
        try:
            suffix = "\n\n❌ Ignored"
            if callback.message.photo:
                cap = (callback.message.caption or "") + suffix
                await callback.message.edit_caption(caption=cap, parse_mode="HTML")
            else:
                base = callback.message.text or ""
                await callback.message.edit_text(base + suffix, parse_mode="HTML")
        except Exception:
            pass

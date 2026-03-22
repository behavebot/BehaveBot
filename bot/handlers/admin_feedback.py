"""Admin-only feedback viewer. Slash command and Admin Panel."""
import csv
import io
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, BufferedInputFile, FSInputFile
from aiogram.filters import Command

from config import ADMIN_IDS
from bot.database.db import (
    get_feedback_last_n,
    get_feedback_all,
    get_all_trades_for_export,
    set_system_setting,
)
from bot.database.models import Trade

router = Router()

ADMIN_ACCESS_DENIED = "Access denied."


def _format_entry(row) -> str:
    fid = row[0]
    uid = row[1]
    text = (row[2] or "(no text)").replace("\n", " ")
    image = row[3] or "(none)"
    created = row[4] or ""
    return f"Feedback #{fid}\nUser ID: {uid}\nText: {text}\nImage: {image}\nDate: {created}\n"


def _format_list(rows) -> str:
    if not rows:
        return "No feedback yet."
    return "\n".join(_format_entry(r) for r in rows)


def _kb_admin_feedback() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="See All Feedback", callback_data="admin_see_all")],
        [InlineKeyboardButton(text="Download CSV", callback_data="admin_download_csv")],
        [InlineKeyboardButton(text="Back to Menu", callback_data="back_home")],
    ])


async def _send_feedback_list_with_previews(chat_id: int, bot, rows: list, reply_markup: InlineKeyboardMarkup) -> None:
    """Send feedback list text then photo preview for each entry that has image_path."""
    text = _format_list(rows)
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
    for row in rows:
        image_path = row[3]
        if image_path and Path(image_path).exists():
            try:
                await bot.send_photo(chat_id=chat_id, photo=FSInputFile(image_path), caption=f"Feedback #{row[0]} preview")
            except Exception:
                pass


@router.message(Command("admin_feedback"))
async def cmd_admin_feedback(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        await message.answer(ADMIN_ACCESS_DENIED)
        return
    rows = await get_feedback_last_n(10)
    await _send_feedback_list_with_previews(message.chat.id, message.bot, rows, _kb_admin_feedback())


@router.callback_query(F.data == "admin_maintenance_menu")
async def admin_maintenance_menu(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    from bot.keyboards import kb_admin_maintenance
    await callback.answer()
    await callback.message.edit_text(
        "🛠 Maintenance\n\nToggle bot availability for non-admin users:",
        reply_markup=kb_admin_maintenance(),
    )


@router.callback_query(F.data == "admin_back_to_admin")
async def admin_back_to_admin(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    from bot.keyboards import kb_admin_panel, ADMIN_PANEL_TEXT
    from bot.database.db import get_user_premium_status_fresh

    await callback.answer()
    st = await get_user_premium_status_fresh(callback.from_user.id)
    await callback.message.edit_text(ADMIN_PANEL_TEXT, reply_markup=kb_admin_panel(bool(st.get("is_premium"))))


@router.callback_query(F.data == "admin_maintenance_off")
async def admin_maintenance_off(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await set_system_setting("maintenance", "off")
    await callback.answer()
    await callback.message.answer("🟢 Bot is ON. Maintenance mode turned off.")


@router.callback_query(F.data == "admin_maintenance_on")
async def admin_maintenance_on(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await set_system_setting("maintenance", "on")
    await callback.answer()
    await callback.message.answer("🔴 Maintenance mode is ON. Non-admin users are blocked.")


@router.callback_query(F.data == "admin_feedback_viewer")
async def admin_feedback_viewer(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    rows = await get_feedback_last_n(10)
    await _send_feedback_list_with_previews(callback.message.chat.id, callback.bot, rows, _kb_admin_feedback())


@router.callback_query(F.data == "admin_see_all")
async def admin_see_all(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    rows = await get_feedback_all()
    buf = io.StringIO()
    for row in rows:
        buf.write(_format_entry(row))
        buf.write("\n")
    content = buf.getvalue().encode("utf-8")
    doc = BufferedInputFile(file=content, filename="feedback_all.txt")
    await callback.message.answer_document(document=doc)


@router.callback_query(F.data == "admin_download_csv")
async def admin_download_csv(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    rows = await get_feedback_all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["feedback_id", "user_id", "text", "image_path", "created_at"])
    for row in rows:
        writer.writerow([row[0], row[1], row[2] or "", row[3] or "", row[4] or ""])
    content = buf.getvalue().encode("utf-8")
    doc = BufferedInputFile(file=content, filename="feedback.csv")
    await callback.message.answer_document(document=doc)


@router.callback_query(F.data == "admin_export_trades")
async def admin_export_trades(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    trades = await get_all_trades_for_export()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "trade_id", "user_id", "token_address", "token_symbol", "open_time", "close_time",
        "open_price", "close_price", "mcap_open", "mcap_close", "duration",
        "emotion_open", "reason_open", "token_category", "risk_level",
        "emotion_close", "reason_close", "discipline", "status",
    ])
    for t in trades:
        writer.writerow([
            t.trade_id, t.user_id, t.token_address, t.token_symbol,
            t.open_time.isoformat() if t.open_time else "",
            t.close_time.isoformat() if t.close_time else "",
            t.open_price, t.close_price or "", t.mcap_open or "", t.mcap_close or "", t.duration or "",
            t.emotion_open or "", t.reason_open or "", t.token_category or "", t.risk_level or "",
            t.emotion_close or "", t.reason_close or "", t.discipline or "", t.status or "",
        ])
    content = buf.getvalue().encode("utf-8")
    doc = BufferedInputFile(file=content, filename="trades_export.csv")
    await callback.message.answer_document(document=doc)

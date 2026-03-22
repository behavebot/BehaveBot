"""
Journal System: Trade Notes and Personal Journal.

Trade Notes: attached to specific trades (via MyStats → Trade Detail). TEXT ONLY. 1 trade = 1 note.
Personal Journal: free journal entries not tied to trades. Supports text + image (two-step flow).
Media must be sent in a single message or one Telegram album (media_group_id); multiple separate messages are rejected.
"""

import asyncio
import json
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

from bot.database.db import (
    insert_trade_note,
    get_trade_note,
    update_trade_note,
    insert_journal_entry,
    get_journal_entries,
    get_journal_entry_count,
    get_journal_entry_by_id,
    update_journal_entry,
    delete_journal_entry,
    get_trade_by_id,
    get_user_timezone_offset,
)
from bot.utils.formatters import format_timestamp_local, format_user_time
from bot.keyboards import kb_back_to_menu
from bot.states import TradeNoteStates, JournalStates
from bot.handlers.ui_flow import show_internal_screen

router = Router()

ENTRIES_PER_PAGE = 5

# Album collection: (user_id, media_group_id) -> {list: [(file_id, type), ...], title, note}
_journal_album_cache: dict[tuple[int, str], dict] = {}
_journal_album_tasks: dict[tuple[int, str], asyncio.Task] = {}
_JOURNAL_ALBUM_DELAY = 1.5


async def _process_journal_album(
    bot,
    storage,
    key,
    user_id: int,
    chat_id: int,
    media_group_id: str,
) -> None:
    await asyncio.sleep(_JOURNAL_ALBUM_DELAY)
    cache_key = (user_id, media_group_id)
    _journal_album_tasks.pop(cache_key, None)
    entry_data = _journal_album_cache.pop(cache_key, None)
    if not entry_data:
        return
    title = entry_data.get("title", "") or "Untitled"
    note_text = entry_data.get("note_text", "") or ""
    items = entry_data.get("list", [])
    if not items:
        return
    first_fid, first_typ = items[0]
    media_file_ids_json = json.dumps([{"file_id": fid, "type": typ} for fid, typ in items])
    await insert_journal_entry(
        user_id=user_id,
        title=title,
        note_text=note_text,
        image_file_id=first_fid,
        media_type=first_typ,
        media_file_ids=media_file_ids_json,
    )
    try:
        from aiogram.fsm.storage.base import BaseStorage
        if isinstance(storage, BaseStorage):
            await storage.set_state(bot=bot, key=key, state=None)
            await storage.set_data(bot=bot, key=key, data={})
    except Exception:
        pass
    msg = "✅ Journal entry saved\n\n📓 Title: " + title + "\n📝 Note: " + (note_text[:200] + "…" if len(note_text) > 200 else note_text or "—") + "\n📷 Media: Attached"
    await bot.send_message(chat_id, msg, reply_markup=kb_back_to_journal())


# =============================================================================
# TRADE NOTES (TEXT ONLY, 1 TRADE = 1 NOTE)
# =============================================================================


def kb_trade_detail_with_note(trade_id: int, has_note: bool = False):
    """Keyboard for trade detail. Shows Edit Note if note exists, else Add Note."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    if has_note:
        b.row(InlineKeyboardButton(text="✏ Edit Note", callback_data=f"edit_trade_note:{trade_id}"))
    else:
        b.row(InlineKeyboardButton(text="📝 Add Note", callback_data=f"add_trade_note:{trade_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Stats", callback_data="stats"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="back_home"))
    return b.as_markup()


def kb_back_to_trade(trade_id: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Trade", callback_data=f"view_trade_detail:{trade_id}"))
    return b.as_markup()


def kb_cancel_note(trade_id: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data=f"cancel_note:{trade_id}"))
    return b.as_markup()


@router.callback_query(F.data.startswith("add_trade_note:"))
async def add_trade_note_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding a note to a trade."""
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.edit_text("Trade not found.", reply_markup=kb_back_to_menu())
        return
    existing_note = await get_trade_note(trade_id, callback.from_user.id)
    if existing_note:
        await callback.message.edit_text(
            "This trade already has a note. Use Edit Note instead.",
            reply_markup=kb_back_to_trade(trade_id),
        )
        return
    await state.update_data(trade_id=trade_id, is_editing=False)
    await state.set_state(TradeNoteStates.waiting_note)
    await callback.message.edit_text(
        "📝 Write your note about this trade:\n\n"
        "Send a text message.",
        reply_markup=kb_cancel_note(trade_id),
    )


@router.callback_query(F.data.startswith("edit_trade_note:"))
async def edit_trade_note_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing a note for a trade."""
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.edit_text("Trade not found.", reply_markup=kb_back_to_menu())
        return
    existing_note = await get_trade_note(trade_id, callback.from_user.id)
    if not existing_note:
        await callback.message.edit_text(
            "No note found for this trade.",
            reply_markup=kb_back_to_trade(trade_id),
        )
        return
    await state.update_data(trade_id=trade_id, is_editing=True)
    await state.set_state(TradeNoteStates.waiting_note)
    current_text = existing_note.get("note_text") or ""
    await callback.message.edit_text(
        f"✏ Edit your note:\n\n"
        f"Current note:\n\"{current_text}\"\n\n"
        f"Send the updated text.",
        reply_markup=kb_cancel_note(trade_id),
    )


@router.callback_query(F.data.startswith("cancel_note:"))
async def cancel_note(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel adding/editing a note."""
    await callback.answer()
    await state.clear()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.message.edit_text("Cancelled.", reply_markup=kb_back_to_menu())
        return
    await callback.message.edit_text("Cancelled.", reply_markup=kb_back_to_trade(trade_id))


@router.message(TradeNoteStates.waiting_note, F.photo | F.document | F.sticker | F.animation)
async def reject_trade_note_media(message: Message, state: FSMContext) -> None:
    """Reject non-text input for trade notes."""
    data = await state.get_data()
    trade_id = data.get("trade_id", 0)
    await message.answer(
        "Trade notes only support text.\n\n"
        "If you want to store charts or screenshots,\n"
        "please use Personal Journal instead.",
        reply_markup=kb_cancel_note(trade_id),
    )


@router.message(TradeNoteStates.waiting_note)
async def receive_trade_note(message: Message, state: FSMContext) -> None:
    """Receive trade note (text only)."""
    data = await state.get_data()
    trade_id = data.get("trade_id")
    is_editing = data.get("is_editing", False)
    if not trade_id:
        await state.clear()
        await message.answer("Something went wrong. Please try again.", reply_markup=kb_back_to_menu())
        return
    note_text = message.text
    if not note_text:
        await message.answer(
            "Trade notes only support text.\n\n"
            "If you want to store charts or screenshots,\n"
            "please use Personal Journal instead.",
            reply_markup=kb_cancel_note(trade_id),
        )
        return
    if is_editing:
        await update_trade_note(trade_id, message.from_user.id, note_text)
        await state.clear()
        await message.answer("✅ Note updated!", reply_markup=kb_back_to_trade(trade_id))
    else:
        await insert_trade_note(
            trade_id=trade_id,
            user_id=message.from_user.id,
            note_text=note_text,
            image_file_id=None,
        )
        await state.clear()
        await message.answer("✅ Note saved!", reply_markup=kb_back_to_trade(trade_id))


@router.callback_query(F.data.startswith("view_trade_detail:"))
async def view_trade_detail(callback: CallbackQuery) -> None:
    """View trade detail with note."""
    await callback.answer()
    try:
        trade_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    trade = await get_trade_by_id(trade_id, callback.from_user.id)
    if not trade:
        await callback.message.edit_text("Trade not found.", reply_markup=kb_back_to_menu())
        return
    from bot.handlers.stats import _fmt_trade_behavior
    from bot.database.db import get_exit_totals_for_trades
    exit_totals = await get_exit_totals_for_trades([trade_id])
    exit_total = exit_totals.get(trade_id, 0.0) or 0.0
    text = _fmt_trade_behavior(trade, exit_total, trade.token_symbol, getattr(trade, "token_name", None))
    note = await get_trade_note(trade_id, callback.from_user.id)
    if note:
        note_text = note.get("note_text") or ""
        text += f"\n\n📝 Note:\n\"{note_text}\""
    await callback.message.edit_text(text, reply_markup=kb_trade_detail_with_note(trade_id, bool(note)))


# =============================================================================
# PERSONAL JOURNAL (TWO-STEP FLOW: TEXT FIRST, THEN OPTIONAL IMAGE)
# =============================================================================


def kb_journal_menu():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✍️ New Entry", callback_data="journal_new_entry"))
    b.row(InlineKeyboardButton(text="📚 View Entries", callback_data="journal_view:0"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="back_home"))
    return b.as_markup()


def kb_journal_entries_list(entries: list, page: int, total_pages: int, total_count: int, tz_offset: int = 0):
    """Keyboard with clickable entry buttons (title — date) and pagination. Date in user local time."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    for i, entry in enumerate(entries):
        title = entry.get("title") or "Untitled"
        raw_ts = entry.get("created_at") or ""
        ts = format_timestamp_local(raw_ts, tz_offset)[:10] if raw_ts else "?"
        has_image = " 📷" if entry["image_file_id"] else ""
        label = f"{title} — {ts}{has_image}"
        if len(label) > 60:
            label = label[:57] + "…"
        b.row(InlineKeyboardButton(
            text=label,
            callback_data=f"journal_entry:{entry['id']}",
        ))
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅ Previous", callback_data=f"journal_view:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Next ➡", callback_data=f"journal_view:{page + 1}"))
    if nav_row:
        b.row(*nav_row)
    b.row(InlineKeyboardButton(text="✍️ New Entry", callback_data="journal_new_entry"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="back_home"))
    return b.as_markup()


def kb_journal_entry_detail(entry_id: int, has_text: bool, has_image: bool):
    """Keyboard: Edit Title, Edit Text, Edit Image, Delete, Back."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏ Edit Title", callback_data=f"journal_edit_title:{entry_id}"))
    if has_text and has_image:
        b.row(InlineKeyboardButton(text="📝 Edit Text", callback_data=f"journal_edit_text:{entry_id}"))
        b.row(InlineKeyboardButton(text="🖼 Edit Image", callback_data=f"journal_edit_image:{entry_id}"))
    elif has_text:
        b.row(InlineKeyboardButton(text="📝 Edit Text", callback_data=f"journal_edit_text:{entry_id}"))
    elif has_image:
        b.row(InlineKeyboardButton(text="🖼 Edit Image", callback_data=f"journal_edit_image:{entry_id}"))
    b.row(InlineKeyboardButton(text="🗑 Delete", callback_data=f"journal_delete_confirm:{entry_id}"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data="back_home"))
    return b.as_markup()


def kb_journal_delete_confirm(entry_id: int):
    """Confirmation keyboard for delete."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Yes", callback_data=f"journal_delete:{entry_id}"),
        InlineKeyboardButton(text="Cancel", callback_data=f"journal_entry:{entry_id}"),
    )
    return b.as_markup()


def kb_cancel_journal():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data="journal_menu"))
    return b.as_markup()


def kb_image_choice():
    """Yes/Skip for attaching image."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="Yes", callback_data="journal_add_image_yes"),
        InlineKeyboardButton(text="Skip", callback_data="journal_add_image_skip"),
    )
    return b.as_markup()


def kb_cancel_image_upload():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data="journal_add_image_skip"))
    return b.as_markup()


def kb_cancel_edit(entry_id: int):
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="❌ Cancel", callback_data=f"journal_entry:{entry_id}"))
    return b.as_markup()


def kb_back_to_journal():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Journal", callback_data="journal_menu"))
    return b.as_markup()


JOURNAL_MENU_TEXT = """📓 Trading Journal

Record your thoughts, lessons, and reflections about your trading journey.

• ✍️ New Entry – Write a new journal entry
• 📚 View Entries – Browse past entries"""


@router.message(Command("journal"))
@router.message(F.text == "📓 Journal")
async def menu_journal(message: Message, state: FSMContext) -> None:
    """Show journal menu (from /journal command or Journal button)."""
    await state.clear()
    await show_internal_screen(message, JOURNAL_MENU_TEXT, kb_journal_menu())


@router.callback_query(F.data == "journal_menu")
async def cb_journal_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show journal menu."""
    await callback.answer()
    await state.clear()
    try:
        await callback.message.edit_text(JOURNAL_MENU_TEXT, reply_markup=kb_journal_menu())
    except Exception:
        await callback.message.answer(JOURNAL_MENU_TEXT, reply_markup=kb_journal_menu())


# --- New Entry Flow: Title → Note text → Optional media ---


def kb_journal_media_choice():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📷 Send Image / Video", callback_data="journal_media_prompt"))
    b.row(InlineKeyboardButton(text="⏭ Skip", callback_data="journal_media_skip"))
    return b.as_markup()


@router.callback_query(F.data == "journal_new_entry")
async def journal_new_entry(callback: CallbackQuery, state: FSMContext) -> None:
    """Step 1: Ask for title."""
    await callback.answer()
    await state.set_state(JournalStates.waiting_title)
    await callback.message.edit_text(
        "Send a title for this journal entry.",
        reply_markup=kb_cancel_journal(),
    )


@router.message(JournalStates.waiting_title)
async def receive_journal_title(message: Message, state: FSMContext) -> None:
    """Step 1: Receive title, then ask for note text only."""
    title = (message.text or "").strip()
    if not title:
        await message.answer(
            "Please send a title (text only).",
            reply_markup=kb_cancel_journal(),
        )
        return
    await state.update_data(journal_title=title)
    await state.set_state(JournalStates.waiting_note)
    await message.answer(
        "Now write your journal note.",
        reply_markup=kb_cancel_journal(),
    )


@router.message(JournalStates.waiting_note, F.photo | F.video)
async def reject_media_in_note(message: Message, state: FSMContext) -> None:
    """Step 2 accepts text only; media comes in Step 3."""
    await message.answer(
        "Please send your note as text first. You can attach an image or video in the next step.",
        reply_markup=kb_cancel_journal(),
    )


@router.message(JournalStates.waiting_note)
async def receive_journal_note(message: Message, state: FSMContext) -> None:
    """Step 2: Receive note text only, then ask for optional media."""
    note_text = (message.text or "").strip()
    if not note_text:
        await message.answer(
            "Please send your journal note as text.",
            reply_markup=kb_cancel_journal(),
        )
        return
    await state.update_data(journal_note_text=note_text)
    await state.set_state(JournalStates.waiting_media)
    await message.answer(
        "Would you like to attach a chart screenshot or video?",
        reply_markup=kb_journal_media_choice(),
    )


@router.callback_query(F.data == "journal_media_prompt", JournalStates.waiting_media)
async def journal_media_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    """Remind user to send image or video."""
    await callback.answer()
    await callback.message.answer(
        "Send your image or video in the next message, or tap Skip to save without media.",
        reply_markup=kb_journal_media_choice(),
    )


@router.callback_query(F.data == "journal_media_skip", JournalStates.waiting_media)
async def journal_media_skip(callback: CallbackQuery, state: FSMContext) -> None:
    """Save entry without media."""
    await callback.answer()
    data = await state.get_data()
    title = data.get("journal_title", "") or "Untitled"
    note_text = data.get("journal_note_text", "") or ""
    await insert_journal_entry(
        user_id=callback.from_user.id,
        title=title,
        note_text=note_text,
        image_file_id=None,
        media_type=None,
    )
    await state.clear()
    msg = "✅ Journal entry saved\n\n📓 Title: " + title + "\n📝 Note: " + (note_text[:200] + "…" if len(note_text) > 200 else note_text or "—") + "\n📷 Media: None"
    await callback.message.edit_text(msg, reply_markup=kb_back_to_journal())


def _journal_media_reject_multi(message: Message):
    """Reject when user sends media in multiple separate messages."""
    return message.answer(
        "⚠️ Please send all images or videos in a single message.\n\n"
        "Example: Send them together as a Telegram album.",
        reply_markup=kb_journal_media_choice(),
    )


@router.message(JournalStates.waiting_media, F.photo)
async def receive_journal_media_photo(message: Message, state: FSMContext) -> None:
    """Step 4: Accept single photo or collect album by media_group_id. Reject multiple separate messages."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await state.get_data()
    title = data.get("journal_title", "") or "Untitled"
    note_text = data.get("journal_note_text", "") or ""
    file_id = message.photo[-1].file_id
    mgid: Optional[str] = getattr(message, "media_group_id", None)
    pending_mgid = data.get("journal_pending_media_group_id")

    if mgid:
        cache_key = (user_id, mgid)
        if pending_mgid is not None and pending_mgid != mgid:
            await _journal_media_reject_multi(message)
            return
        if cache_key not in _journal_album_cache:
            _journal_album_cache[cache_key] = {"list": [], "title": title, "note_text": note_text}
            await state.update_data(journal_pending_media_group_id=mgid)
        _journal_album_cache[cache_key]["list"].append((file_id, "photo"))
        old = _journal_album_tasks.pop(cache_key, None)
        if old and not old.done():
            old.cancel()
        task = asyncio.create_task(
            _process_journal_album(message.bot, state.storage, state.key, user_id, chat_id, mgid)
        )
        _journal_album_tasks[cache_key] = task
        return

    if pending_mgid is not None:
        await _journal_media_reject_multi(message)
        return
    await insert_journal_entry(
        user_id=user_id,
        title=title,
        note_text=note_text,
        image_file_id=file_id,
        media_type="photo",
    )
    await state.clear()
    msg = "✅ Journal entry saved\n\n📓 Title: " + title + "\n📝 Note: " + (note_text[:200] + "…" if len(note_text) > 200 else note_text or "—") + "\n📷 Media: Attached"
    await message.answer(msg, reply_markup=kb_back_to_journal())


@router.message(JournalStates.waiting_media, F.video)
async def receive_journal_media_video(message: Message, state: FSMContext) -> None:
    """Step 4: Accept single video or collect album. Reject multiple separate messages."""
    user_id = message.from_user.id
    chat_id = message.chat.id
    data = await state.get_data()
    title = data.get("journal_title", "") or "Untitled"
    note_text = data.get("journal_note_text", "") or ""
    file_id = message.video.file_id
    mgid = getattr(message, "media_group_id", None)
    pending_mgid = data.get("journal_pending_media_group_id")

    if mgid:
        cache_key = (user_id, mgid)
        if pending_mgid is not None and pending_mgid != mgid:
            await _journal_media_reject_multi(message)
            return
        if cache_key not in _journal_album_cache:
            _journal_album_cache[cache_key] = {"list": [], "title": title, "note_text": note_text}
            await state.update_data(journal_pending_media_group_id=mgid)
        _journal_album_cache[cache_key]["list"].append((file_id, "video"))
        old = _journal_album_tasks.pop(cache_key, None)
        if old and not old.done():
            old.cancel()
        task = asyncio.create_task(
            _process_journal_album(message.bot, state.storage, state.key, user_id, chat_id, mgid)
        )
        _journal_album_tasks[cache_key] = task
        return

    if pending_mgid is not None:
        await _journal_media_reject_multi(message)
        return
    await insert_journal_entry(
        user_id=user_id,
        title=title,
        note_text=note_text,
        image_file_id=file_id,
        media_type="video",
    )
    await state.clear()
    msg = "✅ Journal entry saved\n\n📓 Title: " + title + "\n📝 Note: " + (note_text[:200] + "…" if len(note_text) > 200 else note_text or "—") + "\n📷 Media: Attached"
    await message.answer(msg, reply_markup=kb_back_to_journal())


@router.message(JournalStates.waiting_media)
async def reject_journal_media_other(message: Message, state: FSMContext) -> None:
    """Reject non-image, non-video in media step."""
    await message.answer(
        "Please send an image or video, or tap Skip.",
        reply_markup=kb_journal_media_choice(),
    )


# --- View Entries ---


@router.callback_query(F.data.startswith("journal_view:"))
async def journal_view_entries(callback: CallbackQuery, state: FSMContext) -> None:
    """View journal entries with pagination - clickable buttons."""
    await callback.answer()
    await state.clear()
    try:
        page = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        page = 0
    user_id = callback.from_user.id
    total_count = await get_journal_entry_count(user_id)
    if total_count == 0:
        try:
            await callback.message.edit_text(
                "📓 Your Journal\n\nNo entries yet. Start writing to capture your trading thoughts!",
                reply_markup=kb_journal_menu(),
            )
        except Exception:
            await callback.message.answer(
                "📓 Your Journal\n\nNo entries yet. Start writing to capture your trading thoughts!",
                reply_markup=kb_journal_menu(),
            )
        return
    total_pages = max(1, (total_count + ENTRIES_PER_PAGE - 1) // ENTRIES_PER_PAGE)
    page = max(0, min(page, total_pages - 1))
    entries = await get_journal_entries(user_id, limit=ENTRIES_PER_PAGE, offset=page * ENTRIES_PER_PAGE)
    tz_offset = await get_user_timezone_offset(user_id)
    text = f"📓 Your Journal\n\nPage {page + 1} / {total_pages}\n\nTap an entry to view details:"
    kb = kb_journal_entries_list(entries, page, total_pages, total_count, tz_offset)
    try:
        await callback.message.edit_text(text, reply_markup=kb)
    except Exception:
        await callback.message.answer(text, reply_markup=kb)


# --- Entry Detail ---


@router.callback_query(F.data.startswith("journal_entry:"))
async def journal_entry_detail(callback: CallbackQuery, state: FSMContext) -> None:
    """Show journal entry detail with appropriate edit buttons."""
    await callback.answer()
    await state.clear()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    entry = await get_journal_entry_by_id(entry_id, callback.from_user.id)
    if not entry:
        try:
            await callback.message.edit_text("Entry not found.", reply_markup=kb_back_to_journal())
        except Exception:
            await callback.message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    title = entry.get("title") or "Untitled"
    raw_ts = entry.get("created_at") or ""
    ts = await format_user_time(callback.from_user.id, raw_ts) if raw_ts else "Unknown"
    note_text = entry["note_text"] or ""
    has_text = bool(note_text)
    has_image = bool(entry["image_file_id"])
    if has_text:
        text = f"📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n\"{note_text}\""
    else:
        text = f"📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n(Image only)"
    try:
        await callback.message.delete()
    except Exception:
        pass
    if has_image:
        media_id = entry["image_file_id"]
        kb = kb_journal_entry_detail(entry_id, has_text, has_image)
        if entry.get("media_type") == "video":
            await callback.message.answer_video(
                video=media_id,
                caption=text[:1024],
                reply_markup=kb,
            )
        else:
            await callback.message.answer_photo(
                photo=media_id,
                caption=text[:1024],
                reply_markup=kb,
            )
    else:
        await callback.message.answer(
            text,
            reply_markup=kb_journal_entry_detail(entry_id, has_text, has_image),
        )


# --- Edit Text ---


@router.callback_query(F.data.startswith("journal_edit_text:"))
async def journal_edit_text_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing text of a journal entry."""
    await callback.answer()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    entry = await get_journal_entry_by_id(entry_id, callback.from_user.id)
    if not entry:
        await callback.message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    await state.update_data(editing_entry_id=entry_id)
    await state.set_state(JournalStates.editing_text)
    current_text = entry.get("note_text") or "(No text)"
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        f"✏ Edit text:\n\n"
        f"Current text:\n\"{current_text}\"\n\n"
        f"Send the updated text:",
        reply_markup=kb_cancel_edit(entry_id),
    )


@router.message(JournalStates.editing_text)
async def receive_journal_text_edit(message: Message, state: FSMContext) -> None:
    """Receive updated text for journal entry."""
    data = await state.get_data()
    entry_id = data.get("editing_entry_id")
    if not entry_id:
        await state.clear()
        await message.answer("Something went wrong. Please try again.", reply_markup=kb_back_to_journal())
        return
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    if not entry:
        await state.clear()
        await message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    note_text = message.text
    if not note_text:
        await message.answer(
            "Please send a text message.",
            reply_markup=kb_cancel_edit(entry_id),
        )
        return
    image_file_id = entry.get("image_file_id")
    await update_journal_entry(
        entry_id=entry_id,
        user_id=message.from_user.id,
        note_text=note_text,
        image_file_id=image_file_id,
    )
    await state.clear()
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    title = (entry.get("title") or "Untitled") if entry else "Untitled"
    raw_ts = (entry.get("created_at") or "") if entry else ""
    ts = await format_user_time(message.from_user.id, raw_ts) if raw_ts else "Unknown"
    text = f"✅ Text updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n\"{note_text}\""
    has_text = True
    has_image = bool(image_file_id)
    if has_image:
        kb = kb_journal_entry_detail(entry_id, has_text, has_image)
        if entry.get("media_type") == "video":
            await message.answer_video(video=image_file_id, caption=text[:1024], reply_markup=kb)
        else:
            await message.answer_photo(photo=image_file_id, caption=text[:1024], reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb_journal_entry_detail(entry_id, has_text, has_image))


# --- Edit Title ---


@router.callback_query(F.data.startswith("journal_edit_title:"))
async def journal_edit_title_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing title of a journal entry."""
    await callback.answer()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    entry = await get_journal_entry_by_id(entry_id, callback.from_user.id)
    if not entry:
        await callback.message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    await state.update_data(editing_entry_id=entry_id)
    await state.set_state(JournalStates.editing_title)
    current_title = entry.get("title") or "Untitled"
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "Send the new title for this journal entry.",
        reply_markup=kb_cancel_edit(entry_id),
    )


@router.message(JournalStates.editing_title)
async def receive_journal_title_edit(message: Message, state: FSMContext) -> None:
    """Receive new title and update entry."""
    data = await state.get_data()
    entry_id = data.get("editing_entry_id")
    if not entry_id:
        await state.clear()
        await message.answer("Something went wrong. Please try again.", reply_markup=kb_back_to_journal())
        return
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    if not entry:
        await state.clear()
        await message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    new_title = (message.text or "").strip()
    if not new_title:
        await message.answer(
            "Please send a title (text only).",
            reply_markup=kb_cancel_edit(entry_id),
        )
        return
    await update_journal_entry(
        entry_id=entry_id,
        user_id=message.from_user.id,
        title=new_title,
    )
    await state.clear()
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    title = entry.get("title") or "Untitled"
    raw_ts = entry.get("created_at") or ""
    ts = await format_user_time(message.from_user.id, raw_ts) if raw_ts else "Unknown"
    note_text = entry.get("note_text") or ""
    has_text = bool(note_text)
    has_image = bool(entry.get("image_file_id"))
    if has_text:
        text = f"✅ Title updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n\"{note_text}\""
    else:
        text = f"✅ Title updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n(Image only)"
    if has_image:
        media_id = entry["image_file_id"]
        kb = kb_journal_entry_detail(entry_id, has_text, has_image)
        if entry.get("media_type") == "video":
            await message.answer_video(video=media_id, caption=text[:1024], reply_markup=kb)
        else:
            await message.answer_photo(photo=media_id, caption=text[:1024], reply_markup=kb)
    else:
        await message.answer(text, reply_markup=kb_journal_entry_detail(entry_id, has_text, has_image))


# --- Edit Image ---


@router.callback_query(F.data.startswith("journal_edit_image:"))
async def journal_edit_image_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start editing image of a journal entry."""
    await callback.answer()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    entry = await get_journal_entry_by_id(entry_id, callback.from_user.id)
    if not entry:
        await callback.message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    await state.update_data(editing_entry_id=entry_id)
    await state.set_state(JournalStates.editing_image)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "🖼 Send a new image or video to replace the current media:",
        reply_markup=kb_cancel_edit(entry_id),
    )


@router.message(JournalStates.editing_image, F.photo)
async def receive_journal_image_edit_photo(message: Message, state: FSMContext) -> None:
    """Receive updated photo for journal entry."""
    data = await state.get_data()
    entry_id = data.get("editing_entry_id")
    if not entry_id:
        await state.clear()
        await message.answer("Something went wrong. Please try again.", reply_markup=kb_back_to_journal())
        return
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    if not entry:
        await state.clear()
        await message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    note_text = entry.get("note_text") or ""
    image_file_id = message.photo[-1].file_id
    await update_journal_entry(
        entry_id=entry_id,
        user_id=message.from_user.id,
        note_text=note_text,
        image_file_id=image_file_id,
        media_type="photo",
    )
    await state.clear()
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    title = (entry.get("title") or "Untitled") if entry else "Untitled"
    raw_ts = (entry.get("created_at") or "") if entry else ""
    ts = await format_user_time(message.from_user.id, raw_ts) if raw_ts else "Unknown"
    has_text = bool(note_text)
    if has_text:
        text = f"✅ Image updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n\"{note_text}\""
    else:
        text = f"✅ Image updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}"
    await message.answer_photo(
        photo=image_file_id,
        caption=text[:1024],
        reply_markup=kb_journal_entry_detail(entry_id, has_text, True),
    )


@router.message(JournalStates.editing_image, F.video)
async def receive_journal_image_edit_video(message: Message, state: FSMContext) -> None:
    """Receive updated video for journal entry."""
    data = await state.get_data()
    entry_id = data.get("editing_entry_id")
    if not entry_id:
        await state.clear()
        await message.answer("Something went wrong. Please try again.", reply_markup=kb_back_to_journal())
        return
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    if not entry:
        await state.clear()
        await message.answer("Entry not found.", reply_markup=kb_back_to_journal())
        return
    note_text = entry.get("note_text") or ""
    file_id = message.video.file_id
    await update_journal_entry(
        entry_id=entry_id,
        user_id=message.from_user.id,
        note_text=note_text,
        image_file_id=file_id,
        media_type="video",
    )
    await state.clear()
    entry = await get_journal_entry_by_id(entry_id, message.from_user.id)
    title = (entry.get("title") or "Untitled") if entry else "Untitled"
    raw_ts = (entry.get("created_at") or "") if entry else ""
    ts = await format_user_time(message.from_user.id, raw_ts) if raw_ts else "Unknown"
    has_text = bool(note_text)
    if has_text:
        text = f"✅ Video updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}\n\n\"{note_text}\""
    else:
        text = f"✅ Video updated!\n\n📓 Journal Entry\n\nTitle: {title}\nDate: {ts}"
    await message.answer_video(
        video=file_id,
        caption=text[:1024],
        reply_markup=kb_journal_entry_detail(entry_id, has_text, True),
    )


@router.message(JournalStates.editing_image)
async def reject_non_image_edit(message: Message, state: FSMContext) -> None:
    """Reject non-image, non-video input during media edit."""
    data = await state.get_data()
    entry_id = data.get("editing_entry_id", 0)
    await message.answer(
        "Please send an image or video.",
        reply_markup=kb_cancel_edit(entry_id),
    )


# --- Delete ---


@router.callback_query(F.data.startswith("journal_delete_confirm:"))
async def journal_delete_confirm(callback: CallbackQuery) -> None:
    """Ask confirmation before deleting."""
    await callback.answer()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "Delete this journal entry?",
        reply_markup=kb_journal_delete_confirm(entry_id),
    )


@router.callback_query(F.data.startswith("journal_delete:"))
async def journal_delete(callback: CallbackQuery) -> None:
    """Delete a journal entry."""
    await callback.answer()
    try:
        entry_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        return
    deleted = await delete_journal_entry(entry_id, callback.from_user.id)
    if deleted:
        await callback.message.edit_text("✅ Entry deleted.", reply_markup=kb_back_to_journal())
    else:
        await callback.message.edit_text("Entry not found or already deleted.", reply_markup=kb_back_to_journal())

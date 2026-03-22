"""Admin-only structured announcement builder: step-by-step sections, then optional media, then broadcast."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from bot.database.db import get_all_broadcast_user_ids
from bot.keyboards.inline import BACK_TO_MENU_DATA
from bot.states import AnnouncementStates

router = Router()

ADMIN_ACCESS_DENIED = "Access denied."


def _admin_done_kb() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def _kb_back_to_menu_only() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()

SEP = "━━━━━━━━━━━━━━━━━━"

# Step order and prompts
STEPS = [
    ("waiting_version", "announcement_version", "Enter BehaveBot version.\n\nExample: BehaveBot v1.2"),
    ("waiting_system_update", "announcement_system_update", "Write a short system update summary."),
    ("waiting_new_feature", "announcement_new_feature", "List new features (one message).\n\nExample:\n- Auto DCA System\n- Timezone System"),
    ("waiting_fix", "announcement_fix", "List bug fixes.\n\nExample:\n- Auto read trade bug"),
    ("waiting_improvements", "announcement_improvements", "List improvements.\n\nExample:\n- Better DCA recognition\n- Cleaner pending trade system"),
    ("waiting_note", "announcement_note", "Write an optional note.\n\nExample:\nSome trades may temporarily appear in pending while the system adjusts."),
]


def _build_announcement(data: dict) -> str:
    """Assemble final announcement: clean header, version block only if set, sections with single newline after title, footer."""
    lines = ["🚨 BEHAVEBOT UPDATE", "", SEP]
    version = (data.get("announcement_version") or "").strip()
    if version:
        lines.append(f"version: {version}")
        lines.append(SEP)
        lines.append("")
    sections = [
        ("⚙️ System Update", data.get("announcement_system_update")),
        ("🚀 New Feature", data.get("announcement_new_feature")),
        ("🛠 Fix", data.get("announcement_fix")),
        ("🧠 Improvements", data.get("announcement_improvements")),
        ("⚠️ Note", data.get("announcement_note")),
    ]
    for title, content in sections:
        if content and (content := (content or "").strip()):
            lines.append(title)
            lines.append(content)
            lines.append("")
    lines.append(SEP)
    lines.append("🤖 BehaveBot System")
    lines.append('"Thank you for using BehaveBot".')
    return "\n".join(lines)


def _kb_skip() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⏭ Skip", callback_data="admin_announcement_skip_step"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def _kb_media() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📷 Send Image / Video", callback_data="admin_announcement_media_prompt"))
    b.row(InlineKeyboardButton(text="⏭ Skip", callback_data="admin_announcement_skip_media"))
    b.row(InlineKeyboardButton(text="⬅️ Back to Menu", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def _get_next_step(current_state: str):
    """Return (next_state, data_key, prompt) for the step after current_state."""
    for i, (state_name, data_key, prompt) in enumerate(STEPS):
        if state_name == current_state:
            if i + 1 < len(STEPS):
                return STEPS[i + 1]
            return ("waiting_media", None, None)
    return ("waiting_media", None, None)


async def _ask_step(target, state: FSMContext, state_name: str, prompt: str, is_callback: bool) -> None:
    """Set state and send the step prompt. target is message or callback."""
    await state.set_state(getattr(AnnouncementStates, state_name))
    if is_callback:
        await target.message.edit_text(prompt, reply_markup=_kb_skip())
    else:
        await target.answer(prompt, reply_markup=_kb_skip())


@router.callback_query(F.data == "admin_announcement_start")
async def admin_announcement_start(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    await _ask_step(callback, state, "waiting_version", STEPS[0][2], is_callback=True)


@router.callback_query(F.data == "admin_announcement_skip_step")
async def admin_announcement_skip_step(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    current = await state.get_state()
    if not current:
        return
    state_name = current.split(":")[-1] if ":" in current else current
    data = await state.get_data()
    for sn, dk, _ in STEPS:
        if sn == state_name:
            data[dk] = None
            await state.update_data(data)
            break
    next_info = _get_next_step(state_name)
    next_state, next_key, next_prompt = next_info
    if next_prompt:
        await state.set_state(getattr(AnnouncementStates, next_state))
        await callback.message.edit_text(next_prompt, reply_markup=_kb_skip())
    else:
        await state.set_state(AnnouncementStates.waiting_media)
        await callback.message.edit_text(
            "Attach media? (optional)",
            reply_markup=_kb_media(),
        )


@router.message(AnnouncementStates.waiting_version, F.text)
@router.message(AnnouncementStates.waiting_system_update, F.text)
@router.message(AnnouncementStates.waiting_new_feature, F.text)
@router.message(AnnouncementStates.waiting_fix, F.text)
@router.message(AnnouncementStates.waiting_improvements, F.text)
@router.message(AnnouncementStates.waiting_note, F.text)
async def admin_announcement_receive_section(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    current = await state.get_state()
    state_name = current.split(":")[-1] if current and ":" in current else ""
    data = await state.get_data()
    text = (message.text or "").strip()
    for sn, dk, _ in STEPS:
        if sn == state_name:
            data[dk] = text or None
            await state.update_data(data)
            break
    next_info = _get_next_step(state_name)
    next_state, _, next_prompt = next_info
    if next_prompt:
        await state.set_state(getattr(AnnouncementStates, next_state))
        await message.answer(next_prompt, reply_markup=_kb_skip())
    else:
        await state.set_state(AnnouncementStates.waiting_media)
        await message.answer("Attach media? (optional)", reply_markup=_kb_media())


@router.message(AnnouncementStates.waiting_version)
@router.message(AnnouncementStates.waiting_system_update)
@router.message(AnnouncementStates.waiting_new_feature)
@router.message(AnnouncementStates.waiting_fix)
@router.message(AnnouncementStates.waiting_improvements)
@router.message(AnnouncementStates.waiting_note)
async def admin_announcement_reject_non_text(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer("Please send text or press Skip.", reply_markup=_kb_skip())


@router.callback_query(F.data == "admin_announcement_skip_media", AnnouncementStates.waiting_media)
async def admin_announcement_skip_media(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    data = await state.get_data()
    await state.clear()
    body = _build_announcement(data)
    if len(body) > 4096:
        body = body[:4093] + "..."
    user_ids = await get_all_broadcast_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await callback.bot.send_message(chat_id=uid, text=body)
            sent += 1
        except Exception:
            failed += 1
    await callback.message.edit_text(
        f"✅ Announcement sent.\n\nSent: {sent}\nFailed (blocked/unavailable): {failed}",
        reply_markup=_admin_done_kb(),
    )


@router.message(AnnouncementStates.waiting_media, F.photo)
async def admin_announcement_receive_photo(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    await state.clear()
    body = _build_announcement(data)
    file_id = message.photo[-1].file_id
    user_ids = await get_all_broadcast_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await message.bot.send_photo(chat_id=uid, photo=file_id, caption=body[:1024])
            sent += 1
        except Exception:
            failed += 1
    await message.answer(
        f"✅ Announcement sent with image.\n\nSent: {sent}\nFailed: {failed}",
        reply_markup=_admin_done_kb(),
    )


@router.message(AnnouncementStates.waiting_media, F.video)
async def admin_announcement_receive_video(message: Message, state: FSMContext) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    data = await state.get_data()
    await state.clear()
    body = _build_announcement(data)
    file_id = message.video.file_id
    user_ids = await get_all_broadcast_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await message.bot.send_video(chat_id=uid, video=file_id, caption=body[:1024])
            sent += 1
        except Exception:
            failed += 1
    await message.answer(
        f"✅ Announcement sent with video.\n\nSent: {sent}\nFailed: {failed}",
        reply_markup=_admin_done_kb(),
    )


@router.message(AnnouncementStates.waiting_media)
async def admin_announcement_reject_media(message: Message) -> None:
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(
        "Please send an image or video, or press Skip.",
        reply_markup=_kb_media(),
    )


@router.callback_query(F.data == "admin_announcement_media_prompt", AnnouncementStates.waiting_media)
async def admin_announcement_media_prompt(callback: CallbackQuery) -> None:
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer(ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(
        "Send an image or video now, or press Skip to send text only.",
        reply_markup=_kb_media(),
    )

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from config import FEEDBACK_DIR
from bot.database.db import insert_feedback
from bot.states import FeedbackStates
from bot.keyboards import kb_back_to_menu
from bot.handlers.ui_flow import show_internal_screen

router = Router()

FEEDBACK_PROMPT = "📨 Send your feedback (text and/or image):"
FEEDBACK_SAVED = "✅ Thank you! Your feedback has been saved."


FEEDBACK_VIDEO_BLOCKED = "❌ Video is not allowed. Please send text or image only."


@router.callback_query(F.data == "feedback")
async def start_feedback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FeedbackStates.text)
    await show_internal_screen(callback, FEEDBACK_PROMPT, kb_back_to_menu())


@router.message(FeedbackStates.text, F.video)
async def feedback_video_blocked(message: Message) -> None:
    await message.answer(FEEDBACK_VIDEO_BLOCKED)


@router.message(FeedbackStates.text, F.text)
async def feedback_text(message: Message, state: FSMContext) -> None:
    await state.clear()
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    await insert_feedback(message.from_user.id, message.text, None)
    await message.answer(FEEDBACK_SAVED, reply_markup=kb_back_to_menu())


@router.message(FeedbackStates.text, F.photo)
async def feedback_photo_only(message: Message, state: FSMContext) -> None:
    await state.clear()
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    path = FEEDBACK_DIR / f"{message.from_user.id}_{message.message_id}.jpg"
    await message.bot.download_file(file.file_path, path)
    await insert_feedback(message.from_user.id, None, str(path))
    await message.answer(FEEDBACK_SAVED, reply_markup=kb_back_to_menu())


@router.message(FeedbackStates.text, F.photo, F.caption)
async def feedback_photo_with_caption(message: Message, state: FSMContext) -> None:
    await state.clear()
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    path = FEEDBACK_DIR / f"{message.from_user.id}_{message.message_id}.jpg"
    await message.bot.download_file(file.file_path, path)
    await insert_feedback(message.from_user.id, message.caption or "", str(path))
    await message.answer(FEEDBACK_SAVED, reply_markup=kb_back_to_menu())

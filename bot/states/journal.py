from aiogram.fsm.state import State, StatesGroup


class TradeNoteStates(StatesGroup):
    waiting_note = State()  # waiting for text only (add or edit)


class JournalStates(StatesGroup):
    waiting_title = State()  # Step 1: title for new entry
    waiting_note = State()  # Step 2: note text only
    waiting_media_choice = State()  # Step 3: ask attach image/video or skip
    waiting_media = State()  # Step 4: receive photo/video or skip
    waiting_text = State()  # legacy
    waiting_image_choice = State()
    waiting_image = State()
    editing_text = State()
    editing_image = State()
    editing_title = State()

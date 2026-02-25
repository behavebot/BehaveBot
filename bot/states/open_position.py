from aiogram.fsm.state import State, StatesGroup


class OpenPositionStates(StatesGroup):
    emotion = State()
    emotion_note = State()
    reason = State()
    reason_note = State()
    category = State()
    category_note = State()
    risk = State()


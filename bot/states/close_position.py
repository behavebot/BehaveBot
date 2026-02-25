from aiogram.fsm.state import State, StatesGroup


class ClosePositionStates(StatesGroup):
    emotion = State()
    emotion_note = State()
    reason = State()
    reason_note = State()
    discipline = State()

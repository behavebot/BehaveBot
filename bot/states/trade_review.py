from aiogram.fsm.state import State, StatesGroup


class TradeReviewStates(StatesGroup):
    why_open = State()
    strategy = State()
    emotion = State()
    emotion_note = State()
    notes = State()

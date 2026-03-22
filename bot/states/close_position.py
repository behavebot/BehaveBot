from aiogram.fsm.state import State, StatesGroup


class ClosePositionStates(StatesGroup):
    emotion = State()
    emotion_note = State()
    reason = State()
    reason_note = State()
    discipline = State()
    # Auto-close flow (trade_id in state data)
    auto_emotion_note = State()
    auto_reason_note = State()

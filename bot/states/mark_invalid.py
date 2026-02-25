from aiogram.fsm.state import State, StatesGroup


class MarkInvalidStates(StatesGroup):
    confirm = State()
    reason = State()
    reason_note = State()

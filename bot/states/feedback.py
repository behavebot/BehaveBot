from aiogram.fsm.state import State, StatesGroup


class FeedbackStates(StatesGroup):
    text = State()
    image = State()

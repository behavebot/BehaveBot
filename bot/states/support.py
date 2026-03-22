"""FSM for Contact Support flow."""

from aiogram.fsm.state import State, StatesGroup


class SupportStates(StatesGroup):
    waiting_text = State()
    waiting_image_choice = State()
    waiting_photo = State()
    awaiting_confirm = State()

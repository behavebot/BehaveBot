from aiogram.fsm.state import State, StatesGroup


class AdminPremiumStates(StatesGroup):
    waiting_user_id = State()

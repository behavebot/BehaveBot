from aiogram.fsm.state import State, StatesGroup


class AnnouncementStates(StatesGroup):
    waiting_version = State()
    waiting_system_update = State()
    waiting_new_feature = State()
    waiting_fix = State()
    waiting_improvements = State()
    waiting_note = State()
    waiting_media = State()

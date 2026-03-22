from aiogram.fsm.state import State, StatesGroup


class ConnectWalletStates(StatesGroup):
    address = State()
    network = State()

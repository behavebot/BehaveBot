"""FSM for manual USDC (Base) payment TX submission."""

from aiogram.fsm.state import State, StatesGroup


class PaymentStates(StatesGroup):
    waiting_tx_hash = State()

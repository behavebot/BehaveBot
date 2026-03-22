"""
Single source of truth for Telegram bot commands.
Used by main.py (set_my_commands) and start.py (COMMAND_LIST_TEXT).
"""

from aiogram.types import BotCommand

# (command, description) — no leading slash
COMMAND_LIST = [
    ("start", "Open main menu"),
    ("guide", "How to use bot"),
    ("mystats", "Show trading statistics"),
    ("positions", "Show current open positions"),
    ("settings", "Settings and wallet tracking"),
    ("premium", "Premium features"),
    ("referral", "Earn & Invite"),
    ("journal", "Open trading journal"),
    ("feedback", "Send feedback"),
    ("command_list", "Show command list"),
    ("cancel", "Reset current flow"),
    ("admin", "Admin panel (admins only)"),
]


def get_bot_commands() -> list[BotCommand]:
    """Build BotCommand list for set_my_commands (Telegram menu)."""
    return [BotCommand(command=c, description=d) for c, d in COMMAND_LIST]


def get_command_list_text() -> str:
    """Build in-bot command list text (e.g. for /command_list)."""
    lines = ["🧭 Command List", ""]
    for cmd, desc in COMMAND_LIST:
        lines.append(f"/{cmd} – {desc}")
    return "\n".join(lines)

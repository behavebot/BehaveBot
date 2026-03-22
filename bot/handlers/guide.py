from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.keyboards.inline import BACK_TO_MENU_DATA
from bot.handlers.ui_flow import show_internal_screen

router = Router()

GUIDE_MAIN_MENU = """Learn how to track your trades the right way.

Choose your method below."""

GUIDE_MANUAL = """📝 Manual Trade Guide

Track your trades step by step.

1. Open Position
Enter your trade manually:
• Token
• Entry price
• Reason, strategy, emotion

2. Manage Position
Your trade will appear in My Position.

3. Close Position
When you sell:
• Press Close Position
• Complete closing questions

━━━━━━━━━━

Your data becomes your edge.
Consistency matters."""

GUIDE_AUTO = """🤖 Auto Trade Guide

BehaveBot tracks your trades automatically — no manual input needed.

━━━━━━━━━━

⚙️ Setup (Required)

1. Go to Settings  
2. Add your wallet address  
3. Enable Auto Trade Detection  

Once connected, tracking starts instantly.

━━━━━━━━━━

How it works:

• Buy (Native/USDC → Token)  
→ Bot detects and asks:  
Record / Ignore / Pending  

• Sell (Token → Native/USDC)  
→ Automatically detected as CLOSE  

• Native ↔ Stable  
→ Ignored (not a trade)  

━━━━━━━━━━

Your actions:

Record → Save trade + answer questions  
Ignore → Delete permanently  
No action → Moves to Pending  

━━━━━━━━━━

Smart features:

• DCA is automatic  
(No need to record again)  

• Pending auto-clears (24h)  

━━━━━━━━━━

Only recorded trades affect:

• My Stats  
• AI Insight  
• Performance analysis"""

GUIDE_EARN_INVITE = """🚀 Earn & Invite Guide

Turn your network into real value with BehaveBot.

━━━━━━━━━━

🎁 What you get

Invite a friend → you earn:

• +2 days Premium access  
• Commission from their upgrade  

Your friend gets:

• +1 day Premium access  

━━━━━━━━━━

⏳ Free Premium System

Each account can unlock:

• Up to 3 total free days  
(1 from being invited + 2 from inviting)

After that, only paid or commission applies.

━━━━━━━━━━

💰 Commission System

Your earnings grow with your network:

• 1–5 users → 20%  
• 6–10 users → 35%  
• 10+ users → 50%  

The more active users you bring, the more you earn.

━━━━━━━━━━

📊 How it works

1. Generate your invite link  
2. Share it with other traders  
3. When they join → you both get Premium access  
4. If they upgrade → you earn commission  

━━━━━━━━━━

🧠 Important

• Only Premium users generate earnings  
• Free users only unlock access  
• Referral rewards are tracked automatically  

━━━━━━━━━━

🚀 Why it matters

You're not just using BehaveBot.

You're building a system that pays you back."""

# Backward compatibility for imports expecting single GUIDE string (main menu).
GUIDE = GUIDE_MAIN_MENU


def kb_guide_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 Manual Tracking", callback_data="guide_manual"))
    b.row(InlineKeyboardButton(text="🤖 Auto Tracking", callback_data="guide_auto"))
    b.row(InlineKeyboardButton(text="🚀 Earn & Invite Guide", callback_data="guide_earn_invite"))
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data=BACK_TO_MENU_DATA))
    return b.as_markup()


def kb_guide_back_to_main() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⬅️ Back", callback_data="guide_main"))
    return b.as_markup()


@router.callback_query(F.data == "guide")
async def show_guide(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE_MAIN_MENU, kb_guide_main())


@router.callback_query(F.data == "guide_main")
async def guide_main_cb(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE_MAIN_MENU, kb_guide_main())


@router.callback_query(F.data == "guide_manual")
async def guide_manual_cb(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE_MANUAL, kb_guide_back_to_main())


@router.callback_query(F.data == "guide_auto")
async def guide_auto_cb(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE_AUTO, kb_guide_back_to_main())


@router.callback_query(F.data == "guide_earn_invite")
async def guide_earn_invite_cb(callback: CallbackQuery) -> None:
    await show_internal_screen(callback, GUIDE_EARN_INVITE, kb_guide_back_to_main())

"""Start/help and main menu handlers."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards import main_menu_keyboard
from app.core.constants import CALLBACK_HOME
from app.services import AccessService

router = Router(name="start")

WELCOME_TEXT = (
    "⚖️ JudicialCommentBot\n\n"
    "اختر المادة القانونية. سيبحث البوت عن حكم سعودي مناسب، يتحقق من ملف PDF الأصلي، "
    "يمنع التكرار، ثم ينشئ ملف التعليق Word وفق أسلوب التكليف."
)


@router.message(CommandStart())
async def start(message: Message, access_service: AccessService) -> None:
    user_id = message.from_user.id if message.from_user else 0
    await message.answer(WELCOME_TEXT, reply_markup=main_menu_keyboard(access_service.is_owner(user_id)))


@router.message(Command("help"))
async def help_command(message: Message, access_service: AccessService) -> None:
    user_id = message.from_user.id if message.from_user else 0
    text = "/start — القائمة الرئيسية\n/help — المساعدة"
    if access_service.is_owner(user_id):
        text += "\n\nأوامر المالك:\n/allow <telegram_id>\n/deny <telegram_id>\n/users\n/history"
    await message.answer(text)


@router.callback_query(F.data == CALLBACK_HOME)
async def home(callback: CallbackQuery, access_service: AccessService) -> None:
    if callback.message:
        await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_keyboard(access_service.is_owner(callback.from_user.id)))
    await callback.answer()

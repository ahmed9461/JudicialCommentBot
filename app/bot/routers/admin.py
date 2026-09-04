"""Owner-only allowlist management."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message

from app.core.constants import MAX_ALLOWED_USERS_DISPLAY
from app.services import AccessService

router = Router(name="admin")


def _owner_id(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def _parse_id(command: CommandObject) -> int:
    raw = (command.args or "").strip().split()
    if not raw:
        raise ValueError("missing")
    value = int(raw[0])
    if value <= 0:
        raise ValueError("invalid")
    return value


@router.message(Command("allow"))
async def allow_user(
    message: Message, command: CommandObject, access_service: AccessService
) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    try:
        target = _parse_id(command)
        created = await access_service.add_user(requester, target)
    except (ValueError, TypeError):
        await message.answer("الاستخدام: /allow <telegram_id>")
        return
    await message.answer(
        f"✅ تمت إضافة المستخدم {target}." if created else f"ℹ️ المستخدم {target} مسموح مسبقاً."
    )


@router.message(Command("deny"))
async def deny_user(
    message: Message, command: CommandObject, access_service: AccessService
) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    try:
        target = _parse_id(command)
        removed = await access_service.remove_user(requester, target)
    except ValueError as exc:
        if "Owner" in str(exc):
            await message.answer("⛔ لا يمكن سحب صلاحية المالك.")
        else:
            await message.answer("الاستخدام: /deny <telegram_id>")
        return
    await message.answer(
        f"✅ تم سحب صلاحية المستخدم {target}." if removed else f"ℹ️ المستخدم {target} غير موجود في القائمة."
    )


@router.message(Command("users"))
async def users(message: Message, access_service: AccessService) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    allowed = await access_service.list_users(requester)
    shown = allowed[:MAX_ALLOWED_USERS_DISPLAY]
    lines = [f"👑 المالك: {access_service.owner_id}", "", "المستخدمون المسموحون:"]
    lines.extend(f"• {user_id}" for user_id in shown)
    if not shown:
        lines.append("لا يوجد مستخدمون إضافيون.")
    if len(allowed) > len(shown):
        lines.append(f"… و{len(allowed) - len(shown)} مستخدم إضافي")
    await message.answer("\n".join(lines))


@router.callback_query(F.data == "admin:help")
async def admin_help(callback: CallbackQuery, access_service: AccessService) -> None:
    if not access_service.is_owner(callback.from_user.id):
        await callback.answer("للمالك فقط", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "إدارة المستخدمين بالأوامر:\n"
            "/allow <telegram_id>\n"
            "/deny <telegram_id>\n"
            "/users"
        )
    await callback.answer()

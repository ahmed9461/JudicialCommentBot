"""Owner-only allowlist, history, and catalog status management."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message

from app.catalog import CATALOG_PARSER_VERSION, CatalogStore
from app.core.constants import MAX_ALLOWED_USERS_DISPLAY
from app.db import Database
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
async def allow_user(message: Message, command: CommandObject, access_service: AccessService) -> None:
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
    await message.answer(f"✅ تمت إضافة المستخدم {target}." if created else f"ℹ️ المستخدم {target} مسموح مسبقاً.")


@router.message(Command("deny"))
async def deny_user(message: Message, command: CommandObject, access_service: AccessService) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    try:
        target = _parse_id(command)
        removed = await access_service.remove_user(requester, target)
    except ValueError as exc:
        await message.answer("⛔ لا يمكن سحب صلاحية المالك." if "Owner" in str(exc) else "الاستخدام: /deny <telegram_id>")
        return
    await message.answer(f"✅ تم سحب صلاحية المستخدم {target}." if removed else f"ℹ️ المستخدم {target} غير موجود في القائمة.")


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
    await message.answer("\n".join(lines))


@router.message(Command("history"))
async def history(message: Message, access_service: AccessService, database: Database) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    rows = await database.recent_history(20)
    if not rows:
        await message.answer("لا توجد قضايا مستخدمة حتى الآن.")
        return
    parts = ["📜 آخر القضايا المستخدمة:"]
    for index, row in enumerate(rows, 1):
        parts.append(
            f"\n{index}) {row['case_number'] or 'بلا رقم'} — {row['court_name'] or 'محكمة غير متوفرة'}\n"
            f"المادة: {row['subject_slug']} | التقييم: {row['suitability_score'] or 0}/100\n"
            f"التاريخ: {row['used_at']}"
        )
    await message.answer("\n".join(parts))


@router.message(Command("catalog"))
async def catalog_status(message: Message, access_service: AccessService, catalog_store: CatalogStore) -> None:
    requester = _owner_id(message)
    if not access_service.is_owner(requester):
        await message.answer("⛔ هذا الأمر للمالك فقط.")
        return
    verified = await catalog_store.stats(parser_version=CATALOG_PARSER_VERSION)
    total = await catalog_store.stats()
    if verified.cases == 0:
        stale_note = ""
        if total.cases:
            stale_note = f"\nيوجد {total.cases} سجلًا من جيل فهرسة أقدم، لكنها معطلة ولا تدخل البحث."
        await message.answer(
            "🗂️ الفهرس القضائي المتحقق غير جاهز بعد.\n"
            f"جيل الفهرسة الحالي: v{CATALOG_PARSER_VERSION}."
            f"{stale_note}\n\n"
            "شغّل/اترك خدمة تحديث الفهرس حتى تكتمل. لن يستخدم البوت سجلات قديمة بدلًا من ذلك."
        )
        return
    await message.answer(
        "🗂️ حالة الفهرس القضائي المتحقق:\n"
        f"جيل الفهرسة: v{CATALOG_PARSER_VERSION}\n"
        f"القضايا الجاهزة: {verified.cases}\n"
        f"المجموعات الجاهزة: {verified.collections}\n"
        f"الجهات الرسمية: {verified.sources}\n\n"
        "البحث يستخدم هذا الجيل فقط؛ أي سجلات من قواعد فهرسة أقدم لا تُعرض ولا تُستخدم."
    )


@router.callback_query(F.data == "admin:help")
async def admin_help(callback: CallbackQuery, access_service: AccessService) -> None:
    if not access_service.is_owner(callback.from_user.id):
        await callback.answer("للمالك فقط", show_alert=True)
        return
    if callback.message:
        await callback.message.answer(
            "إدارة البوت:\n/allow <telegram_id>\n/deny <telegram_id>\n/users\n/history\n/catalog"
        )
    await callback.answer()

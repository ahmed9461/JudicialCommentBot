"""Owner and allowlist authorization service."""

from app.db import Database


class AccessService:
    def __init__(self, owner_id: int, database: Database) -> None:
        self.owner_id = owner_id
        self.database = database

    def is_owner(self, telegram_id: int) -> bool:
        return telegram_id == self.owner_id

    async def is_allowed(self, telegram_id: int) -> bool:
        if self.is_owner(telegram_id):
            return True
        return await self.database.is_allowed_user(telegram_id)

    async def add_user(self, requester_id: int, telegram_id: int) -> bool:
        self._require_owner(requester_id)
        if telegram_id <= 0:
            raise ValueError("Telegram ID must be positive")
        if telegram_id == self.owner_id:
            return False
        return await self.database.add_allowed_user(telegram_id, requester_id)

    async def remove_user(self, requester_id: int, telegram_id: int) -> bool:
        self._require_owner(requester_id)
        if telegram_id == self.owner_id:
            raise ValueError("Owner access cannot be removed")
        return await self.database.remove_allowed_user(telegram_id)

    async def list_users(self, requester_id: int) -> list[int]:
        self._require_owner(requester_id)
        return await self.database.list_allowed_users()

    def _require_owner(self, requester_id: int) -> None:
        if not self.is_owner(requester_id):
            raise PermissionError("Owner permission is required")

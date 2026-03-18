from __future__ import annotations

from typing import Any


class AuthService:
    def __init__(self, database: Any):
        self.database = database

    def sync_user(self, user: Any) -> None:
        username = getattr(user, "username", None)
        first_name = getattr(user, "first_name", "") or ""
        last_name = getattr(user, "last_name", "") or ""
        display_name = " ".join(part for part in [first_name, last_name] if part).strip() or username
        self.database.ensure_user(user.id, username=username, display_name=display_name)

    def is_whitelisted(self, user_id: int) -> bool:
        return self.database.is_whitelisted(user_id)

    def is_admin(self, user_id: int) -> bool:
        return self.database.is_admin(user_id)

    def whitelist_user(self, user_id: int) -> None:
        self.database.whitelist_user(user_id)


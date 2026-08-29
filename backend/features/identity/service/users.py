"""Identity use cases and their existing transaction boundaries."""

from sqlalchemy.orm import Session

from core.errors import ConflictError, NotFoundError
from features.identity.repository import UserRepository
from infrastructure.database.dbo.User import User


class UserService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = UserRepository(session)

    def list(self) -> list[User]:
        return self._repository.list()

    def update(
        self,
        user_id: str,
        *,
        username: str | None,
        role: str | None,
        is_deleted: bool | None,
    ) -> str:
        user = self._require_user(user_id)
        if self._would_remove_last_admin(user, role, is_deleted):
            raise ConflictError("Cannot remove the last administrator")
        if username:
            user.username = username
        if role:
            user.role = role
        if is_deleted is not None:
            user.is_deleted = is_deleted
        self._session.commit()
        self._repository.refresh(user)
        return f"User {user.username} updated successfully"

    def change_password(self, user_id: str, password: str) -> str:
        user = self._repository.get_active(user_id)
        if user is None:
            raise NotFoundError("User not found")
        user.set_password(password)
        self._session.commit()
        self._repository.refresh(user)
        return f"User {user.username} password updated successfully"

    def delete(self, user_id: str) -> str:
        user = self._repository.get_active(user_id)
        if user is None:
            raise NotFoundError("User not found")
        if user.role == "admin" and self._repository.active_admin_count() <= 1:
            raise ConflictError("Cannot delete the last administrator")
        user.is_deleted = True
        self._session.commit()
        self._repository.refresh(user)
        return f"User {user.username} deleted successfully"

    def authenticate_local(self, username: str, password: str) -> User | None:
        user = self._repository.get_local_account(username)
        if user is None or not user.check_password(password):
            return None
        return user

    def get_by_username(self, username: str) -> User | None:
        return self._repository.get_by_username(username)

    def record_login(self, user_id: str) -> None:
        self._repository.add_login_record(user_id)
        self._session.commit()

    def _require_user(self, user_id: str) -> User:
        user = self._repository.get(user_id)
        if user is None:
            raise NotFoundError("User not found")
        return user

    def _would_remove_last_admin(
        self, user: User, role: str | None, is_deleted: bool | None
    ) -> bool:
        removing_admin = user.role == "admin" and (role == "user" or is_deleted is True)
        return removing_admin and self._repository.active_admin_count() <= 1


def user_service(session: Session) -> UserService:
    return UserService(session)

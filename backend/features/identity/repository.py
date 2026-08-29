"""Concrete database access for identity records."""

from typing import cast

from sqlalchemy.orm import Session

from infrastructure.database.dbo.LoginRecord import LoginRecord
from infrastructure.database.dbo.User import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[User]:
        return cast(list[User], self._session.query(User).all())

    def get(self, user_id: str) -> User | None:
        return self._session.query(User).filter(User.id == user_id).first()

    def get_active(self, user_id: str) -> User | None:
        return (
            self._session.query(User)
            .filter(User.id == user_id)
            .filter(User.is_deleted == False)  # noqa: E712 - SQLAlchemy clause
            .first()
        )

    def get_local_account(self, username: str) -> User | None:
        return (
            self._session.query(User)
            .filter(User.username == username)
            .filter(User.oauth_provider == None)  # noqa: E711 - SQLAlchemy clause
            .filter(User.oauth_id == None)  # noqa: E711 - SQLAlchemy clause
            .filter(User.is_deleted == False)  # noqa: E712 - SQLAlchemy clause
            .first()
        )

    def get_by_username(self, username: str) -> User | None:
        return self._session.query(User).filter(User.username == username).first()

    def active_admin_count(self) -> int:
        return cast(
            int,
            self._session.query(User)
            .filter(User.role == "admin", User.is_deleted.is_not(True))
            .count(),
        )

    def add_login_record(self, user_id: str) -> None:
        self._session.add(LoginRecord(user_id=user_id))

    def refresh(self, user: User) -> None:
        self._session.refresh(user)

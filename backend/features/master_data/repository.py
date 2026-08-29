"""Concrete database access for master-data records."""

from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import and_
from sqlalchemy.orm import Session

from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Topic import Topic


class ChannelRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[Channel]:
        return cast(list[Channel], self._session.query(Channel).all())

    def get(self, channel_id: int) -> Channel | None:
        return self._session.query(Channel).filter(Channel.id == channel_id).first()

    def get_by_name(self, name: str) -> Channel | None:
        return self._session.query(Channel).filter(Channel.name == name).first()

    def add(self, channel: Channel) -> None:
        self._session.add(channel)

    def delete(self, channel: Channel) -> None:
        self._session.delete(channel)

    def refresh(self, channel: Channel) -> None:
        self._session.refresh(channel)


class DepartmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[Department]:
        return cast(list[Department], self._session.query(Department).all())

    def get(self, department_id: int) -> Department | None:
        return (
            self._session.query(Department)
            .filter(Department.id == department_id)
            .first()
        )

    def get_by_name(self, name: str) -> Department | None:
        return self._session.query(Department).filter(Department.name == name).first()

    def add(self, department: Department) -> None:
        self._session.add(department)

    def delete(self, department: Department) -> None:
        self._session.delete(department)

    def refresh(self, department: Department) -> None:
        self._session.refresh(department)


class DeliveryServiceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[DeliveryService]:
        return cast(list[DeliveryService], self._session.query(DeliveryService).all())

    def get(self, delivery_service_id: int) -> DeliveryService | None:
        return (
            self._session.query(DeliveryService)
            .filter(DeliveryService.id == delivery_service_id)
            .first()
        )

    def get_by_name(self, name: str) -> DeliveryService | None:
        return (
            self._session.query(DeliveryService)
            .filter(DeliveryService.name == name)
            .first()
        )

    def add(self, delivery_service: DeliveryService) -> None:
        self._session.add(delivery_service)

    def delete(self, delivery_service: DeliveryService) -> None:
        self._session.delete(delivery_service)

    def refresh(self, delivery_service: DeliveryService) -> None:
        self._session.refresh(delivery_service)


class TopicRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self) -> list[Topic]:
        return cast(list[Topic], self._session.query(Topic).all())

    def get(self, topic_id: int) -> Topic | None:
        return self._session.query(Topic).filter(Topic.id == topic_id).first()

    def get_by_value(self, value: str) -> Topic | None:
        return self._session.query(Topic).filter(Topic.topic == value).first()

    def add(self, topic: Topic) -> None:
        self._session.add(topic)

    def delete(self, topic: Topic) -> None:
        self._session.delete(topic)

    def refresh(self, topic: Topic) -> None:
        self._session.refresh(topic)


class StoreRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list(self, conditions: Sequence[Any], *, ordered: bool = False) -> list[Store]:
        query = self._session.query(Store).filter(and_(*conditions))
        if ordered:
            query = query.order_by(Store.store_key)
        return cast(list[Store], query.all())

    def get(self, store_key: int) -> Store | None:
        return self._session.query(Store).filter(Store.store_key == store_key).first()

    def add(self, store: Store) -> None:
        self._session.add(store)

    def merge(self, store: Store) -> None:
        self._session.merge(store)

    def refresh(self, store: Store) -> None:
        self._session.refresh(store)

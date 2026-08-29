"""Use cases and transaction boundaries for master-data records."""

import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from core.errors import NotFoundError, ValidationError
from core.time import utc_now
from features.master_data.repository import (
    ChannelRepository,
    DeliveryServiceRepository,
    DepartmentRepository,
    StoreRepository,
    TopicRepository,
)
from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Topic import Topic


class ChannelService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = ChannelRepository(session)

    def list(self) -> list[Channel]:
        return self._repository.list()

    def get(self, channel_id: int) -> Channel:
        channel = self._repository.get(channel_id)
        if channel is None:
            raise NotFoundError("Channel not found")
        return channel

    def create(self, name: str) -> Channel:
        if self._repository.get_by_name(name) is not None:
            raise ValidationError("Channel already exists")
        channel = Channel(name=name)
        self._repository.add(channel)
        self._session.commit()
        self._repository.refresh(channel)
        return channel

    def update(self, channel_id: int, name: str) -> Channel:
        channel = self.get(channel_id)
        channel.name = name
        self._session.commit()
        self._repository.refresh(channel)
        return channel

    def delete(self, channel_id: int) -> str:
        channel = self.get(channel_id)
        name = channel.name
        self._repository.delete(channel)
        self._session.commit()
        return f"Channel {name} deleted successfully"


class DepartmentService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = DepartmentRepository(session)

    def list(self) -> list[Department]:
        return self._repository.list()

    def get(self, department_id: int) -> Department:
        department = self._repository.get(department_id)
        if department is None:
            raise NotFoundError("Department not found")
        return department

    def create(self, name: str) -> Department:
        if self._repository.get_by_name(name) is not None:
            raise ValidationError("Department already exists")
        department = Department(name=name)
        self._repository.add(department)
        self._session.commit()
        self._repository.refresh(department)
        return department

    def update(self, department_id: int, name: str) -> Department:
        department = self.get(department_id)
        department.name = name
        self._session.commit()
        self._repository.refresh(department)
        return department

    def delete(self, department_id: int) -> None:
        department = self.get(department_id)
        self._repository.delete(department)
        self._session.commit()


class DeliveryServiceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = DeliveryServiceRepository(session)

    def list(self) -> list[DeliveryService]:
        return self._repository.list()

    def get(self, delivery_service_id: int) -> DeliveryService:
        delivery_service = self._repository.get(delivery_service_id)
        if delivery_service is None:
            raise NotFoundError("Delivery service not found")
        return delivery_service

    def create(self, name: str) -> DeliveryService:
        if self._repository.get_by_name(name) is not None:
            raise ValidationError("Delivery service already exists")
        delivery_service = DeliveryService(name=name)
        self._repository.add(delivery_service)
        self._session.commit()
        self._repository.refresh(delivery_service)
        return delivery_service

    def update(self, delivery_service_id: int, name: str) -> DeliveryService:
        delivery_service = self.get(delivery_service_id)
        delivery_service.name = name
        self._session.commit()
        self._repository.refresh(delivery_service)
        return delivery_service

    def delete(self, delivery_service_id: int) -> str:
        delivery_service = self.get(delivery_service_id)
        name = delivery_service.name
        self._repository.delete(delivery_service)
        self._session.commit()
        return f"Delivery service {name} deleted successfully"


class TopicService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = TopicRepository(session)

    def list(self) -> list[Topic]:
        return self._repository.list()

    def get(self, topic_id: int) -> Topic:
        topic = self._repository.get(topic_id)
        if topic is None:
            raise NotFoundError("Topic not found")
        return topic

    def create(self, value: str) -> Topic:
        if self._repository.get_by_value(value) is not None:
            raise ValidationError("Topic already exists")
        topic = Topic(topic=value)
        self._repository.add(topic)
        self._session.commit()
        self._repository.refresh(topic)
        return topic

    def update(self, topic_id: int, value: str) -> Topic:
        topic = self.get(topic_id)
        topic.topic = value
        self._session.commit()
        self._repository.refresh(topic)
        return topic

    def delete(self, topic_id: int) -> str:
        topic = self.get(topic_id)
        value = topic.topic
        self._repository.delete(topic)
        self._session.commit()
        return f"Topic {value} deleted successfully"


class StoreService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = StoreRepository(session)

    def list(self, conditions: Sequence[Any], *, ordered: bool = False) -> list[Store]:
        return self._repository.list(conditions, ordered=ordered)

    def get(self, store_key: int) -> Store:
        store = self._repository.get(store_key)
        if store is None:
            raise NotFoundError("Store not found")
        return store

    def create(self, values: Mapping[str, Any]) -> Store:
        store_key = values["store_key"]
        if store_key and self._repository.get(store_key) is not None:
            raise ValidationError("Store id already exists")
        store = Store(**dict(values))
        self._repository.add(store)
        self._session.commit()
        self._repository.refresh(store)
        return store

    def close(self, store_key: int) -> None:
        store = self.get(store_key)
        store.is_closed = True
        self._session.commit()

    def upsert_csv(self, file: Any) -> dict[str, str]:
        tmp_file_path: str | None = None
        try:
            tmp_file_name = f"{utc_now().strftime('%Y%m%d%H%M%S')}_{file.filename}"
            tmp_file_path = os.path.join("/tmp", tmp_file_name)
            with open(tmp_file_path, "wb") as temporary_file:
                temporary_file.write(file.file.read())
            dataframe = pd.read_csv(
                tmp_file_path,
                encoding="utf-8",
                sep=",",
                encoding_errors="ignore",
                on_bad_lines="warn",
                engine="python",
                quotechar='"',
                escapechar="\\",
                na_values=[""],
            ).replace({np.nan: None})
            for _, row in dataframe.iterrows():
                store = Store(
                    store_key=row["store_key"],
                    store_name_english=row.get("store_name_english"),
                    store_name_local=row.get("store_name_local"),
                    bu_key=row.get("bu_key"),
                    area_manager=row.get("area_manager"),
                    store_format=row.get("store_format"),
                    store_type=row.get("store_type"),
                    operations_controller=row.get("operations_controller"),
                    regional_manager=row.get("regional_manager"),
                    px=row.get("px"),
                    csr=row.get("csr"),
                    dr=row.get("dr"),
                    mag_type=row.get("mag_type"),
                    cf_grouping=row.get("cf_grouping"),
                    store_brand=row.get("store_brand"),
                    competitor=row.get("competitor"),
                    region=row.get("region"),
                    area=row.get("area"),
                    province=row.get("province"),
                    territory=row.get("territory"),
                    toh=row.get("toh"),
                    district=row.get("district"),
                    city=row.get("city"),
                    operations_manager=row.get("operations_manager"),
                    district_manager=row.get("district_manager"),
                    sic=row.get("sic"),
                    soc=row.get("soc"),
                    tech_life_type=row.get("tech_life_type"),
                    operation_manager_tl=row.get("operation_manager_tl"),
                    region_manager_tl=row.get("region_manager_tl"),
                    relocation=row.get("relocation"),
                    latitude=row.get("latitude"),
                    longitude=row.get("longitude"),
                    store_open_date=(
                        datetime.strptime(row.get("store_open_date"), "%Y-%m-%d").date()
                        if row.get("store_open_date")
                        else None
                    ),
                    store_close_date=(
                        datetime.strptime(
                            row.get("store_close_date"), "%Y-%m-%d"
                        ).date()
                        if row.get("store_close_date")
                        else None
                    ),
                    is_closed=True if row.get("is_closed") == "True" else False,
                )
                self._repository.merge(store)
            self._session.commit()
            return {"message": "Stores upserted successfully"}
        except Exception:
            self._session.rollback()
            raise
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)


def channel_service(session: Session) -> ChannelService:
    return ChannelService(session)


def department_service(session: Session) -> DepartmentService:
    return DepartmentService(session)


def delivery_service_service(session: Session) -> DeliveryServiceService:
    return DeliveryServiceService(session)


def topic_service(session: Session) -> TopicService:
    return TopicService(session)


def store_service(session: Session) -> StoreService:
    return StoreService(session)

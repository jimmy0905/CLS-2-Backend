"""Public request and response contracts for master-data endpoints."""

from datetime import date

from pydantic import BaseModel


class ChannelResponse(BaseModel):
    id: int
    name: str


class CreateChannelRequest(BaseModel):
    name: str


class UpdateChannelRequest(BaseModel):
    name: str


class DeliveryServiceResponse(BaseModel):
    id: int
    name: str


class CreateDeliveryServiceRequest(BaseModel):
    name: str


class UpdateDeliveryServiceRequest(BaseModel):
    name: str


class CreateDepartmentRequest(BaseModel):
    name: str


class UpdateDepartmentRequest(BaseModel):
    name: str


class CreateTopicRequest(BaseModel):
    topic: str


class UpdateTopicRequest(BaseModel):
    topic: str


class StoreResponse(BaseModel):
    store_key: int
    store_name_english: str | None = None
    store_name_local: str | None = None
    bu_key: str | None = None
    area_manager: str | None = None
    store_format: str | None = None
    store_type: str | None = None
    operations_controller: str | None = None
    regional_manager: str | None = None
    px: str | None = None
    csr: str | None = None
    dr: str | None = None
    mag_type: str | None = None
    cf_grouping: str | None = None
    store_brand: str | None = None
    competitor: str | None = None
    region: str | None = None
    area: str | None = None
    province: str | None = None
    territory: str | None = None
    toh: str | None = None
    district: str | None = None
    city: str | None = None
    operations_manager: str | None = None
    district_manager: str | None = None
    sic: str | None = None
    # ALTER TABLE stores ADD COLUMN soc VARCHAR(100) NULL;
    soc: str | None = None
    tech_life_type: str | None = None
    operation_manager_tl: str | None = None
    region_manager_tl: str | None = None
    relocation: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    store_open_date: date | None = None
    store_close_date: date | None = None
    is_closed: bool


class CreateStoreRequest(BaseModel):
    store_key: int
    store_name_english: str | None = None
    store_name_local: str | None = None
    bu_key: str | None = None
    area_manager: str | None = None
    store_format: str | None = None
    store_type: str | None = None
    operations_controller: str | None = None
    regional_manager: str | None = None
    px: str | None = None
    csr: str | None = None
    dr: str | None = None
    mag_type: str | None = None
    cf_grouping: str | None = None
    store_brand: str | None = None
    competitor: str | None = None
    region: str | None = None
    area: str | None = None
    province: str | None = None
    territory: str | None = None
    toh: str | None = None
    district: str | None = None
    city: str | None = None
    operations_manager: str | None = None
    district_manager: str | None = None
    sic: str | None = None
    soc: str | None = None
    tech_life_type: str | None = None
    operation_manager_tl: str | None = None
    region_manager_tl: str | None = None
    relocation: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    store_open_date: date | None = None
    store_close_date: date | None = None
    is_closed: bool

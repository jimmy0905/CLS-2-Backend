from utils.database import Base
from sqlalchemy import Column, Integer, String, Index, Boolean, Double, Date
from sqlalchemy.orm import relationship

class Store(Base):
    __tablename__ = "stores"

    store_key= Column(Integer, primary_key=True) # store_key
    store_name_english = Column(String(100)) # store_name_english
    store_name_local=Column(String(100), nullable=True) # store_name_local
    bu_key = Column(String(100)) # bu_key
    area_manager=Column(String(100), nullable=True) # area_manager
    store_format=Column(String(100), nullable=True) # store_format
    store_type=Column(String(100), nullable=True) # store_type
    operations_controller=Column(String(100), nullable=True) # operations_controller
    regional_manager=Column(String(100), nullable=True) # regional_manager
    px=Column(String(100), nullable=True) # px
    csr=Column(String(100), nullable=True) # csr
    dr=Column(String(100), nullable=True) # dr
    mag_type=Column(String(100), nullable=True) # mag_type
    cf_grouping=Column(String(100), nullable=True) # cf_grouping
    store_brand=Column(String(100), nullable=True) # store_brand
    competitor=Column(String(100), nullable=True) # competitor
    region=Column(String(100), nullable=True) # region
    area=Column(String(100), nullable=True) # area
    # TODO: Add province to the database
    # ALTER TABLE stores ADD COLUMN province VARCHAR(100) NULL;
    province=Column(String(100), nullable=True) # province
    territory=Column(String(100), nullable=True) # territory
    toh=Column(String(100), nullable=True) # toh
    district=Column(String(100), nullable=True) # district
    city=Column(String(100), nullable=True) # city
    operations_manager=Column(String(100), nullable=True) # operations_manager
    district_manager=Column(String(100), nullable=True) # district_manager
    sic=Column(String(100), nullable=True) # sic
    # TODO: Add soc to the database
    # ALTER TABLE stores ADD COLUMN soc VARCHAR(100) NULL;
    soc=Column(String(100), nullable=True) # soc
    tech_life_type=Column(String(100), nullable=True) # tech_life_type
    operation_manager_tl=Column(String(100), nullable=True) # operation_manager_tl
    region_manager_tl=Column(String(100), nullable=True) # region_manager_tl
    relocation=Column(String(100), nullable=True) # relocation
    latitude=Column(Double, nullable=True) # latitude
    longitude=Column(Double, nullable=True) # longitude
    store_open_date=Column(Date, nullable=True) # store_open_date
    store_close_date=Column(Date, nullable=True) # store_close_date
    is_closed=Column(Boolean, default=True) # is_closed

    surveys = relationship("Survey", back_populates="store")

    # Indexes for filtered columns
    __table_args__ = (Index("idx_store_name_english", store_name_english),)

    def to_dict(self):
        return {
            "store_key": self.store_key,
            "store_name_english": self.store_name_english,
            "store_name_local": self.store_name_local,
            "bu_key": self.bu_key,
            "area_manager": self.area_manager,
            "store_format": self.store_format,
            "store_type": self.store_type,
            "operations_controller": self.operations_controller,
            "regional_manager": self.regional_manager,
            "px": self.px,
            "csr": self.csr,
            "dr": self.dr,
            "mag_type": self.mag_type,
            "cf_grouping": self.cf_grouping,
            "store_brand": self.store_brand,
            "competitor": self.competitor,
            "region": self.region,
            "area": self.area,
            "province": self.province,
            "territory": self.territory,
            "toh": self.toh,
            "district": self.district,
            "city": self.city,
            "operations_manager": self.operations_manager,
            "district_manager": self.district_manager,
            "sic": self.sic,
            "soc": self.soc,
            "tech_life_type": self.tech_life_type,
            "operation_manager_tl": self.operation_manager_tl,
            "region_manager_tl": self.region_manager_tl,
            "relocation": self.relocation,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "store_open_date": self.store_open_date,
            "store_close_date": self.store_close_date,
            "is_closed": self.is_closed,
        }

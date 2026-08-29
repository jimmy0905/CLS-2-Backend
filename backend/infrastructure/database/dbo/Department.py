from infrastructure.database.base import Base
from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import relationship


class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True)

    # Relationships
    survey_departments = relationship("SurveyDepartments", back_populates="department")
    surveys = relationship(
        "Survey",
        secondary="survey_departments",
        back_populates="departments",
        viewonly=True,
    )

    # Indexes for filtered columns
    __table_args__ = (Index("idx_department_name", name),)

    def to_dict(self):
        return {"id": self.id, "name": self.name}

"""Import every SQLAlchemy mapping before metadata or migrations are inspected."""

from infrastructure.database.base import Base
from infrastructure.database.dbo.AnalyticsAuditLog import AnalyticsAuditLog
from infrastructure.database.dbo.AnalyticsChart import AnalyticsChart
from infrastructure.database.dbo.AnalyticsExportJob import AnalyticsExportJob
from infrastructure.database.dbo.AnalyticsField import AnalyticsField
from infrastructure.database.dbo.AnalyticsFieldValue import AnalyticsFieldValue
from infrastructure.database.dbo.AnalyticsMetric import AnalyticsMetric
from infrastructure.database.dbo.AnalyticsModelVersion import AnalyticsModelVersion
from infrastructure.database.dbo.AnalyticsQueryLog import AnalyticsQueryLog
from infrastructure.database.dbo.Channel import Channel
from infrastructure.database.dbo.DeliveryService import DeliveryService
from infrastructure.database.dbo.Department import Department
from infrastructure.database.dbo.Keyword import Keyword
from infrastructure.database.dbo.Store import Store
from infrastructure.database.dbo.Survey import Survey
from infrastructure.database.dbo.SurveyDepartments import SurveyDepartments
from infrastructure.database.dbo.SurveyKeywords import SurveyKeywords
from infrastructure.database.dbo.SurveyTopics import SurveyTopics
from infrastructure.database.dbo.Topic import Topic
from infrastructure.database.dbo.UploadTask import UploadTask
from infrastructure.database.dbo.UploadTaskError import UploadTaskError

__all__ = [
    "AnalyticsAuditLog",
    "AnalyticsChart",
    "AnalyticsExportJob",
    "AnalyticsField",
    "AnalyticsFieldValue",
    "AnalyticsMetric",
    "AnalyticsModelVersion",
    "AnalyticsQueryLog",
    "Base",
    "Channel",
    "DeliveryService",
    "Department",
    "Keyword",
    "Store",
    "Survey",
    "SurveyDepartments",
    "SurveyKeywords",
    "SurveyTopics",
    "Topic",
    "UploadTask",
    "UploadTaskError",
]

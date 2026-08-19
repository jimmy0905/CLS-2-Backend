from models.UploadTask import UploadTask
from models.Survey import Survey
import pandas as pd
import json
from models.Store import Store
from models.UploadTaskError import UploadTaskError
from models.Department import Department
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from models.Channel import Channel
from models.DeliveryService import DeliveryService
from datetime import datetime
from utils.llm.extract_total import extract_total, _extract_total_retry_sync
from utils.llm.normalize_keywords import normalize_keywords, _normalize_keywords_sync
from utils.logger import logger
from utils.utc import as_utc, utc_now
import dateutil.parser
from typing import Union, Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import asyncio
import time
from functools import partial
from sqlalchemy.orm import sessionmaker
from utils.database import engine
from config import MAX_WORKER_THREADS
from utils.llm.models import TotalResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import os

# Thread-safe lock for updating progress
progress_lock = threading.Lock()


# ONLY FOR WTCHKECLS PROJECT
def is_total_valid(total: TotalResponse) -> tuple[bool, str]:
    """
    Check if the total is valid.
    for these five topics, if dept select= Supply Chain only, then the topics chart should only show the topics below

    Packaging/Condition of Delivered Items
    Deliveryman Service
    Communication of Order Status
    Order Arrived at Promised Time
    Store Staff’s Service
    """
    if total.departments == ["Supply Chain"]:
        for topic in total.topics:
            if topic.text not in [
                "Packaging/Condition of Delivered Items",
                "Deliveryman Service",
                "Communication of Order Status",
                "Order Arrived at Promised Time",
                "Store Staff’s Service",
            ]:
                return (
                    False,
                    f"Department {total.departments} only, but Topic {topic.text} is not valid",
                )
    return True, ""


def is_comment_valid(comment: str) -> bool:
    """
    Check if the comment is valid.
    """

    # Handle None or empty comments
    if not comment or pd.isna(comment):
        return False

    # Convert to string and strip whitespace
    comment_str = str(comment).strip()

    # Define stop words that indicate invalid comments
    # These should match the comment exactly (case-insensitive) or be very similar
    stop_words = ["na", "n/a", "nan", "none", "null"]

    # Check if comment is exactly one of the stop words
    for stop_word in stop_words:
        if comment_str.lower() == stop_word.lower():
            return False

    # Check for comments that are just punctuation or very short
    if comment_str in [".", "...", "-", "沒有"]:
        return False

    # Check if comment is just whitespace or special characters
    if not comment_str or comment_str.isspace():
        return False

    return True


def parse_flexible_date(
    date_input: Union[str, datetime, pd.Timestamp], row_number: int = None
) -> Optional[datetime]:
    """
    Parse date formats into a timezone-aware UTC datetime.

    Only supports these specific formats:
    - 'YYYY-MM-DD HH:MM:SS' (e.g., '2025-09-01 10:04:57') - interpreted as UTC
    - 'YYYY-MM-DDTHH:MM:SS.000Z' (e.g., '2025-09-01T10:04:57.000Z') - UTC timezone

    Args:
        date_input: The date value to parse
        row_number: Optional row number for logging context

    Returns:
        Timezone-aware UTC datetime object or None if parsing fails
    """
    if not date_input or pd.isna(date_input):
        return None

    row_context = f"Row {row_number}: " if row_number else ""

    try:
        # If it's already a datetime object
        if isinstance(date_input, datetime):
            return as_utc(date_input)

        # If it's a pandas Timestamp, convert to datetime
        if isinstance(date_input, pd.Timestamp):
            dt = date_input.to_pydatetime()
            return as_utc(dt)

        # Convert to string for parsing
        date_str = str(date_input).strip()

        # Handle ISO format with Z (UTC timezone)
        if date_str.endswith("Z"):
            try:
                return as_utc(datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%fZ"))
            except ValueError:
                logger.debug(
                    f"{row_context}Failed to parse date '{date_str}' using ISO format with Z"
                )

        # Handle simple datetime format (assume UTC)
        try:
            return as_utc(datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            logger.debug(
                f"{row_context}Failed to parse date '{date_str}' using simple format"
            )

        # If all parsing attempts fail
        logger.warning(
            f"{row_context}Date '{date_str}' does not match required formats: 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DDTHH:MM:SS.000Z'"
        )
        return None

    except Exception as e:
        logger.error(f"{row_context}Unexpected error parsing date '{date_input}': {e}")
        return None


def parse_optional_cls(row: Any, row_number: int = None) -> Optional[float]:
    """Read the nullable CLS score, accepting the legacy CSL source spelling."""
    for column_name in ("CLS", "CSL", "cls", "csl"):
        if column_name not in row:
            continue

        value = row[column_name]
        if pd.isna(value):
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            row_context = f"Row {row_number}: " if row_number is not None else ""
            logger.warning(f"{row_context}Invalid CLS score '{value}', storing null")
            return None

    return None

async def process_single_row(
    row_data: Dict[str, Any],
    upload_task_id: int,
    available_topics: List[str],
    available_departments: List[str],
    db: Session,
) -> Dict[str, Any]:
    """
    Process a single row in a separate thread.
    Updates statistics directly with thread-safe locks.
    Returns a dictionary with processing results.
    """
    try:
        index = row_data["index"]
        row = row_data["row"]

        # Serialize row data
        try:
            row_dict = row.to_dict()
            json_row_data = json.dumps({"index": index, "row": row_dict}, default=str)
        except Exception as e:
            logger.warning(f"Row {index + 1}: Failed to serialize row data: {e}")
            json_row_data = json.dumps({"index": index, "error": str(e)})

        have_to_retry = False
        result = {"index": index, "success": False, "error": None}

        # Handle NaN values for critical fields
        store_key = row["store_key"] if pd.notna(row["store_key"]) else None
        comment = row["answer"] if pd.notna(row["answer"]) else None
        reported_at = row["survey_order_date"] if pd.notna(row["survey_order_date"]) else None
        cls = parse_optional_cls(row, index + 1)
        is_deleted_value = row["is_delete"] if "is_delete" in row and pd.notna(row["is_delete"]) else None
        logger.info(f"Row {index + 1}: Is deleted value: {is_deleted_value}")
        # Handle survey_id - can be int, float, or string (hash)
        if pd.notna(row["survey_id"]):
            survey_id_raw = row["survey_id"]
            if isinstance(survey_id_raw, (int, float)):
                survey_id = str(int(survey_id_raw))
            else:
                survey_id = str(survey_id_raw)
        else:
            survey_id = None
        
        # Handle respondent_id - can be int, float, or string (hash)
        if pd.notna(row["respondent_id"]):
            respondent_id_raw = row["respondent_id"]
            if isinstance(respondent_id_raw, (int, float)):
                respondent_id = str(int(respondent_id_raw))
            else:
                respondent_id = str(respondent_id_raw)
        else:
            respondent_id = None
        logger.info(f"Row {index + 1}: Survey ID: {survey_id}, Respondent ID: {respondent_id}, Is deleted: {is_deleted_value}")
        if is_deleted_value and is_deleted_value == "Y":
            is_deleted = True
        else:
            is_deleted = False
        logger.info(f"Row {index + 1}: Is deleted: {is_deleted}")
        if is_deleted:
            #Check of the survey_id and respondent_id is in the database
            existing_survey = db.query(Survey).filter(
                Survey.survey_id == survey_id,
                Survey.respondent_id == respondent_id
            ).first()
            if existing_survey:
                # Update existing survey with new data and mark as deleted
                existing_survey.is_deleted = True
                existing_survey.cls = cls
                db.commit()

            # Update processed rows count for successful deleted-row handling
            with progress_lock:
                upload_task = (
                    db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
                )
                if upload_task:
                    upload_task.processed_rows += 1
                    processed_count = upload_task.processed_rows
                    total_rows = upload_task.total_rows
                    db.commit()

                    if (processed_count % 10 == 0) or (processed_count == total_rows):
                        logger.info(f"Processed {processed_count}/{total_rows} rows")

            result["success"] = True
            result["error"] = "Survey is deleted"
            return result
        
        if is_comment_valid(comment) is False:
            logger.warning(f"Row {index + 1}: Comment is invalid, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Comment is invalid",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = "Comment is invalid"
            return result

        # Handle NaN values for channel and delivery_mode (optional fields)
        channel_name = None
        if "channel" in row and pd.notna(row["channel"]):
            channel_name = row["channel"]

        delivery_service_name = None
        if "processed_delivery_mode_detail" in row and pd.notna(row["processed_delivery_mode_detail"]):
            delivery_service_name = row["processed_delivery_mode_detail"]

        # Check if the store_key (store_key) is valid
        # Check if the store_key is empty
        if not store_key:
            logger.warning(f"Row {index + 1}: Store Key is empty, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Store Key is required",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = "Store Key is required"
            return result
        # Check if the store_key is in the database
        # Handle store_key - can be int, float, or string
        try:
            if isinstance(store_key, (int, float)):
                store_key_value = int(store_key)
            else:
                store_key_value = int(float(store_key))
        except (ValueError, TypeError):
            logger.warning(f"Row {index + 1}: Invalid store_key format: {store_key}")
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message=f"Invalid store_key format: {store_key}",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = "Invalid store_key format"
            return result
        
        store = db.query(Store).filter(Store.store_key == store_key_value).first()
        if not store:
            logger.info(
                f"Row {index + 1}: Store Key {store_key} not found in database, creating new store"
            )
            try:
                store = Store(
                    store_key=store_key_value,
                    store_name_local=str(store_key),
                )
                db.add(store)
                db.commit()
                db.refresh(store)
            except IntegrityError:
                db.rollback()
                store = db.query(Store).filter(Store.store_key == store_key_value).first()

        # Check if the comment is valid
        # Check if the comment is empty
        if not comment:
            logger.warning(f"Row {index + 1}: Comment is empty, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Comment is required",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = "Comment is required"
            return result
        # Check if the reported_at is valid
        # Check if the reported_at is empty
        if not reported_at:
            logger.warning(f"Row {index + 1}: Reported date is empty, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Reported at is required",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = "Reported at is required"
            return result
        # Check if the reported_at is a valid date using flexible parsing
        parsed_date = parse_flexible_date(reported_at, index + 1)

        if parsed_date is None:
            logger.warning(
                f"Row {index + 1}: Could not parse date '{reported_at}', skipping row"
            )
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_key=store_key,
                input_comment=comment,
                input_reported_at=str(reported_at),
                error_message=f"Could not parse date format: {reported_at}",
                raw_row_data=json_row_data,
            )
            db.add(error)
            db.commit()
            result["error"] = f"Could not parse date format: {reported_at}"
            return result

        reported_at = parsed_date

        # Check if the channel_name is not empty and not None, then get the channel_id
        if channel_name is not None and str(channel_name).strip():
            channel = db.query(Channel).filter(Channel.name == channel_name).first()
            if not channel:
                # Create a new channel if it doesn't exist
                channel = Channel(name=channel_name)
                db.add(channel)
                db.commit()
                db.refresh(channel)
            channel_id = channel.id
        else:
            channel_id = None
        # Check if the delivery_service_name is not empty and not None, then get the delivery_service_id
        if delivery_service_name is not None and str(delivery_service_name).strip():
            delivery_service = (
                db.query(DeliveryService)
                .filter(DeliveryService.name == delivery_service_name)
                .first()
            )
            if not delivery_service:
                delivery_service = DeliveryService(name=delivery_service_name)
                db.add(delivery_service)
                db.commit()
                db.refresh(delivery_service)
            delivery_service_id = delivery_service.id
        else:
            delivery_service_id = None

        # Topic (Survey sentiment, topics, departments, keywords)
        llm_processing_failed = False
        llm_error_message = None
        total_topics = None
        total_departments = None
        total_sentiment = None
        total_keywords = None
        
        try:
            # Use synchronous extract_total in thread pool
            from utils.llm.extract_total import _extract_total_sync

            total, _ = await asyncio.to_thread(_extract_total_sync, comment)

            # ONLY FOR WTCHKECLS PROJECT
            # Check if the total is valid
            is_valid, error_message = is_total_valid(total)
            if not is_valid:
                llm_processing_failed = True
                llm_error_message = error_message
            else:
                # if total.cannot_classified is True, set have_to_retry to True
                if total.cannot_classified:
                    logger.warning(
                        f"Row {index + 1}: Cannot classified in AI Analysis after first try, retrying..."
                    )
                    have_to_retry = True
                # Normalize keywords
                if not have_to_retry:
                    normalized_total, _ = await asyncio.to_thread(_normalize_keywords_sync, comment, total.model_dump())
                else:
                    normalized_total = total
                # Check if the topics are not empty
                if normalized_total.topics is None or len(normalized_total.topics) == 0:
                    logger.warning(f"Row {index + 1}: Topics are empty after first try, skipping row")
                    have_to_retry = True
                # Check if the departments are not empty
                if normalized_total.departments is None or len(normalized_total.departments) == 0:
                    logger.warning(f"Row {index + 1}: Departments are empty after first try, skipping row")
                    have_to_retry = True
                # Check if the keywords are not empty
                if normalized_total.keywords is None or len(normalized_total.keywords) == 0:
                    logger.warning(f"Row {index + 1}: Keywords are empty after first try, skipping row")
                    have_to_retry = True
                # Check if the topics are valid
                for topic in normalized_total.topics:
                    if topic.text not in available_topics:
                        logger.warning(
                            f"Row {index + 1}: Topic {topic.text} is not valid after first try, retrying..."
                        )
                        have_to_retry = True
                # Check if the departments are valid
                for department in normalized_total.departments:
                    if department.text not in available_departments:
                        logger.warning(
                            f"Row {index + 1}: Department {department.text} is not valid after first try, retrying..."
                        )
                        have_to_retry = True

                if have_to_retry:
                    total, _ = await asyncio.to_thread(_extract_total_retry_sync, comment)
                    if total.cannot_classified:
                        logger.warning(
                            f"Row {index + 1}: Cannot classified in AI Analysis after retrying, skipping row"
                        )
                        llm_processing_failed = True
                        llm_error_message = "Cannot classified in AI Analysis after retrying"
                    else:
                        # Normalize keywords
                        normalized_total, _ = await asyncio.to_thread(_normalize_keywords_sync, comment, total.model_dump())
                        # Check if the total is classified, if not, skip the row
                        if normalized_total.cannot_classified:
                            logger.warning(
                                f"Row {index + 1}: Cannot classified in AI Analysis after retrying, skipping row"
                            )
                            llm_processing_failed = True
                            llm_error_message = "Cannot classified in AI Analysis after retrying"
                        # Check if the topics are not empty
                        elif normalized_total.topics is None:
                            logger.warning(
                                f"Row {index + 1}: Topics are empty after retrying, skipping row"
                            )
                            llm_processing_failed = True
                            llm_error_message = "Topics are empty after retrying"
                        # Check if the departments are not empty
                        elif normalized_total.departments is None:
                            logger.warning(
                                f"Row {index + 1}: Departments are empty after retrying, skipping row"
                            )
                            llm_processing_failed = True
                            llm_error_message = "Departments are empty after retrying"
                        # Check if the keywords are not empty
                        elif normalized_total.keywords is None:
                            logger.warning(
                                f"Row {index + 1}: Keywords are empty after retrying, skipping row"
                            )
                            llm_processing_failed = True
                            llm_error_message = "Keywords are empty after retrying"
                        else:
                            # Check if the topics are valid
                            for topic in normalized_total.topics:
                                if topic.text not in available_topics:
                                    logger.warning(
                                        f"Row {index + 1}: Topic {topic.text} is not valid after retrying, skipping row"
                                    )
                                    llm_processing_failed = True
                                    llm_error_message = f"Topic {topic.text} is not valid after retrying"
                                    break
                            
                            # Check if the departments are valid (only if topics were valid)
                            if not llm_processing_failed:
                                for department in normalized_total.departments:
                                    if department.text not in available_departments:
                                        logger.warning(
                                            f"Row {index + 1}: Department {department.text} is not valid after retrying, skipping row"
                                        )
                                        llm_processing_failed = True
                                        llm_error_message = f"Department {department.text} is not valid after retrying"
                                        break

                if not llm_processing_failed:
                    total_topics = normalized_total.topics
                    total_departments = normalized_total.departments
                    total_sentiment = normalized_total.overall_sentiment.upper() if normalized_total.overall_sentiment else None
                    total_keywords = normalized_total.keywords if normalized_total.keywords else []

        except Exception as e:
            logger.error(
                f"Row {index + 1}: Failed to extract topics and sentiment. Error: {e}"
            )
            llm_processing_failed = True
            llm_error_message = f"Error conducting AI Analysis for topics: {e}"
        
        # If LLM processing failed, check if we need to update an existing record
        if llm_processing_failed:
            # Check if survey already exists
            existing_survey = db.query(Survey).filter(
                Survey.survey_id == survey_id,
                Survey.respondent_id == respondent_id
            ).first()
            
            if existing_survey:
                # Update existing survey with new data and mark as deleted
                logger.info(
                    f"Row {index + 1}: LLM processing failed but found existing survey (ID: {existing_survey.id}), updating and marking as deleted..."
                )
                existing_survey.store_key = store_key
                existing_survey.comment = comment
                existing_survey.reported_at = reported_at
                existing_survey.cls = cls
                existing_survey.channel_id = channel_id
                existing_survey.delivery_service_id = delivery_service_id
                existing_survey.raw_row_data = json_row_data
                existing_survey.is_deleted = True
                
                db.commit()
                
                # Log the error
                error = UploadTaskError(
                    upload_task_id=upload_task_id,
                    input_store_key=store_key,
                    input_comment=comment,
                    input_reported_at=reported_at,
                    error_message=llm_error_message,
                    raw_row_data=json_row_data,
                )
                db.add(error)
                db.commit()
                
                # Update processed rows count
                with progress_lock:
                    upload_task = (
                        db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
                    )
                    if upload_task:
                        upload_task.processed_rows += 1
                        processed_count = upload_task.processed_rows
                        total_rows = upload_task.total_rows
                        db.commit()

                        if (processed_count % 10 == 0) or (processed_count == total_rows):
                            logger.info(f"Processed {processed_count}/{total_rows} rows")
                
                result["success"] = True
                result["error"] = f"Updated existing survey with is_deleted=True due to: {llm_error_message}"
                logger.info(
                    f"Row {index + 1}: Updated existing survey (ID: {existing_survey.id}) and marked as deleted"
                )
                return result
            else:
                # No existing survey, just log the error
                error = UploadTaskError(
                    upload_task_id=upload_task_id,
                    input_store_key=store_key,
                    input_comment=comment,
                    input_reported_at=reported_at,
                    error_message=llm_error_message,
                    raw_row_data=json_row_data,
                )
                db.add(error)
                db.commit()
                result["error"] = llm_error_message
                return result

        # Check if survey already exists (upsert logic)
        existing_survey = db.query(Survey).filter(
            Survey.survey_id == survey_id,
            Survey.respondent_id == respondent_id
        ).first()

        if existing_survey:
            # Update existing survey
            logger.info(
                f"Row {index + 1}: Found existing survey (ID: {existing_survey.id}) with survey_id={survey_id} and respondent_id={respondent_id}, updating..."
            )
            existing_survey.store_key = store_key
            existing_survey.comment = comment
            existing_survey.reported_at = reported_at
            existing_survey.cls = cls
            existing_survey.sentiment = total_sentiment
            existing_survey.channel_id = channel_id
            existing_survey.delivery_service_id = delivery_service_id
            existing_survey.raw_row_data = json_row_data
            existing_survey.is_deleted = False
            
            # Delete old relationships to replace with new analysis
            db.query(SurveyKeywords).filter(SurveyKeywords.survey_id == existing_survey.id).delete()
            db.query(SurveyTopics).filter(SurveyTopics.survey_id == existing_survey.id).delete()
            db.query(SurveyDepartments).filter(SurveyDepartments.survey_id == existing_survey.id).delete()
            
            db.commit()
            survey = existing_survey
            logger.debug(
                f"Row {index + 1}: Survey updated successfully with ID: {survey.id}"
            )
        else:
            # Create a new survey
            survey = Survey(
                survey_id=survey_id,
                respondent_id=respondent_id,
                store_key=store_key,
                comment=comment,
                reported_at=reported_at,
                cls=cls,
                sentiment=total_sentiment,
                channel_id=channel_id,
                delivery_service_id=delivery_service_id,
                raw_row_data=json_row_data,
            )
            db.add(survey)
            db.commit()
            db.refresh(survey)
            logger.debug(
                f"Row {index + 1}: Survey created successfully with ID: {survey.id}"
            )

        # Add keywords
        for keyword_obj in total_keywords:
            # Get or create keyword
            keyword = (
                db.query(Keyword).filter(Keyword.keyword == keyword_obj.text.lower()).first()
            )
            if not keyword:
                logger.debug(
                    f"Row {index + 1}: Creating new keyword: {keyword_obj.text.lower()}"
                )
                keyword = Keyword(keyword=keyword_obj.text.lower())
                db.add(keyword)
                db.commit()
                db.refresh(keyword)
            else:
                logger.debug(
                    f"Row {index + 1}: Using existing keyword: {keyword_obj.text}"
                )

            # Create survey-keyword relationship
            survey_keyword = SurveyKeywords(
                survey_id=survey.id,
                keyword_id=keyword.id,
                sentiment=keyword_obj.sentiment.upper() if keyword_obj.sentiment else None,
            )
            db.add(survey_keyword)
            db.flush()

        # Add topics
        for topic_obj in total_topics:
            # Get or create topic
            topic = db.query(Topic).filter(Topic.topic == topic_obj.text).first()
            if not topic:
                logger.debug(f"Row {index + 1}: Creating new topic: {topic_obj.text}")
                topic = Topic(topic=topic_obj.text)
                db.add(topic)
                db.commit()
                db.refresh(topic)
            else:
                logger.debug(f"Row {index + 1}: Using existing topic: {topic_obj.text}")

            # Create survey-topic relationship
            survey_topic = SurveyTopics(
                survey_id=survey.id,
                topic_id=topic.id,
                sentiment=topic_obj.sentiment.upper() if topic_obj.sentiment else None,
            )
            db.add(survey_topic)
            db.flush()

        # Add departments
        for department_obj in total_departments:
            # Get or create department
            department = (
                db.query(Department)
                .filter(Department.name == department_obj.text)
                .first()
            )
            if not department:
                logger.debug(
                    f"Row {index + 1}: Creating new department: {department_obj.text}"
                )
                department = Department(name=department_obj.text)
                db.add(department)
                db.commit()
                db.refresh(department)
            else:
                logger.debug(
                    f"Row {index + 1}: Using existing department: {department_obj.text}"
                )

            # Create survey-department relationship
            survey_department = SurveyDepartments(
                survey_id=survey.id,
                department_id=department.id,
                sentiment=department_obj.sentiment.upper() if department_obj.sentiment else None,
            )
            db.add(survey_department)

        db.commit()

        # Update processed rows count atomically
        with progress_lock:
            upload_task = (
                db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            )
            if upload_task:
                upload_task.processed_rows += 1
                processed_count = upload_task.processed_rows
                total_rows = upload_task.total_rows
                db.commit()

                # Log progress every 10 processed items or at completion
                if (processed_count % 10 == 0) or (processed_count == total_rows):
                    logger.info(f"Processed {processed_count}/{total_rows} rows")

        result["success"] = True
        logger.debug(
            f"Row {index + 1}: Successfully processed survey with ID: {survey.id}"
        )
        return result

    except Exception as e:
        logger.error(f"Row {index + 1}: Unexpected error during processing: {e}")
        result["error"] = f"Unexpected error: {e}"
        return result
    finally:
        db.close()


async def process_upload_task(file_path, db, upload_task_id):
    """
    Process upload task with multi-threading support.
    Uses ThreadPoolExecutor to process multiple rows concurrently.
    """
    try:
        # Get the available topics and departments from the database
        topics = db.query(Topic).all()
        available_topics = [topic.topic for topic in topics]
        departments = db.query(Department).all()
        available_departments = [department.name for department in departments]

        # Read the file from csv file with improved error handling
        try:
            df = pd.read_csv(
                file_path,
                encoding="utf-8",
                sep=",",
                encoding_errors="ignore",
                on_bad_lines="warn",  # Warn about bad lines but continue
                engine="python",  # Use Python engine for more flexible parsing
                quotechar='"',
                escapechar='\\',
                na_values=['']
            )
            logger.info(f"Successfully parsed CSV file with {len(df)} rows for processing")
        except Exception as e:
            logger.error(f"Failed to read CSV file {file_path}: {e}")
            raise Exception(f"Failed to read CSV file: {e}")

        # Prepare row data for processing
        row_data_list = []
        for index, row in df.iterrows():
            row_data_list.append({"index": index, "row": row})

        # Configure thread pool size - adjust based on your system capabilities
        # Consider API rate limits and database connection pool size
        max_workers = min(MAX_WORKER_THREADS, len(row_data_list))

        logger.info(
            f"Processing {len(row_data_list)} rows with {max_workers} worker threads"
        )

        # Track processing time
        start_time = time.time()

        # Create a session factory for thread-safe database access
        SessionLocal = sessionmaker(bind=engine)
        
        # Synchronous wrapper function to run async process_single_row in a thread
        def process_row_sync(row_data, upload_task_id, available_topics, available_departments):
            thread_db = SessionLocal()
            try:
                # Create a new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(
                        process_single_row(row_data, upload_task_id, available_topics, available_departments, thread_db)
                    )
                finally:
                    loop.close()
            finally:
                thread_db.close()
        
        # Process rows in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_row = {
                executor.submit(
                    process_row_sync,
                    row_data,
                    upload_task_id,
                    available_topics,
                    available_departments,
                ): row_data["index"]
                for row_data in row_data_list
            }

            # Wait for all tasks to complete
            completed_tasks = 0
            failed_tasks = 0

            for future in as_completed(future_to_row):
                row_index = future_to_row[future]
                try:
                    result = future.result()
                    if result.get("success"):
                        completed_tasks += 1
                    else:
                        failed_tasks += 1

                except Exception as e:
                    failed_tasks += 1
                    logger.error(f"Error processing row {row_index + 1}: {e}")

        # Update final task status
        upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
        if upload_task:
            upload_task.status = "completed"
            upload_task.updated_at = utc_now()
            db.commit()

        # Calculate and log performance metrics
        end_time = time.time()
        processing_time = end_time - start_time
        rows_per_second = len(row_data_list) / processing_time if processing_time > 0 else 0

        # Get final statistics from database
        final_upload_task = (
            db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
        )
        final_processed_count = final_upload_task.processed_rows if final_upload_task else 0

        logger.info(
            f"Upload task {upload_task_id} completed in {processing_time:.2f} seconds."
        )
        logger.info(
            f"Processed {final_processed_count}/{len(row_data_list)} rows successfully."
        )
        logger.info(f"Failed tasks: {failed_tasks}, Completed tasks: {completed_tasks}")
        logger.info(
            f"Processing rate: {rows_per_second:.2f} rows/second with {max_workers} threads."
        )
    except Exception as e:
        logger.error(f"Failed to process upload task {upload_task_id}: {e}")
        raise Exception(f"Failed to process upload task: {e}")
    finally:
        #Remove the upload task file
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Failed to remove upload task file {file_path}: {e}")

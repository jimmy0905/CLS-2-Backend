from models.UploadTask import UploadTask
from models.Survey import Survey
import pandas as pd
from models.Store import Store
from models.UploadTaskError import UploadTaskError
from models.Department import Department
from models.Topic import Topic
from models.Keyword import Keyword
from models.SurveyTopics import SurveyTopics
from models.SurveyKeywords import SurveyKeywords
from models.SurveyDepartments import SurveyDepartments
from datetime import datetime
from utils.llm.extract_total import extract_total
from utils.logger import logger
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


def parse_flexible_date(
    date_input: Union[str, datetime, pd.Timestamp], row_number: int = None
) -> Optional[datetime]:
    """
    Parse various date formats into a datetime object.

    Supports:
    - Standard formats: 'YYYY-MM-DD HH:MM:SS', 'YYYY-MM-DD'
    - US formats: 'MM/DD/YY HH:MM', 'MM/DD/YYYY HH:MM'
    - European formats: 'DD/MM/YY HH:MM', 'DD/MM/YYYY HH:MM'
    - ISO formats: ISO 8601 formats
    - Pandas Timestamp objects
    - Python datetime objects

    Args:
        date_input: The date value to parse
        row_number: Optional row number for logging context

    Returns:
        datetime object or None if parsing fails
    """
    if not date_input or pd.isna(date_input):
        return None

    row_context = f"Row {row_number}: " if row_number else ""

    try:
        # If it's already a datetime object, return as is
        if isinstance(date_input, datetime):
            return date_input

        # If it's a pandas Timestamp, convert to datetime
        if isinstance(date_input, pd.Timestamp):
            return date_input.to_pydatetime()

        # Convert to string for parsing
        date_str = str(date_input).strip()

        # List of common date formats to try in order
        date_formats = [
            # Standard formats
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            # US formats (MM/DD/YY, MM/DD/YYYY)
            "%m/%d/%y %H:%M",
            "%m/%d/%Y %H:%M",
            "%m/%d/%y",
            "%m/%d/%Y",
            # European formats (DD/MM/YY, DD/MM/YYYY)
            "%d/%m/%y %H:%M",
            "%d/%m/%Y %H:%M",
            "%d/%m/%y",
            "%d/%m/%Y",
            # Alternative separators
            "%m-%d-%y %H:%M",
            "%m-%d-%Y %H:%M",
            "%d-%m-%y %H:%M",
            "%d-%m-%Y %H:%M",
            # ISO formats
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S.%fZ",
        ]

        # Try each format
        for date_format in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, date_format)
                return parsed_date
            except ValueError:
                logger.debug(
                    f"{row_context}Failed to parse date '{date_str}' using format '{date_format}'"
                )
                continue

        # If manual parsing fails, try dateutil parser (more flexible but slower)
        try:
            parsed_date = dateutil.parser.parse(date_str)
            return parsed_date
        except (ValueError, TypeError) as e:
            logger.debug(
                f"{row_context}dateutil parser also failed for '{date_str}': {e}"
            )

        # If all parsing attempts fail
        logger.warning(
            f"{row_context}Failed to parse date '{date_str}' with all available formats"
        )
        return None

    except Exception as e:
        logger.error(f"{row_context}Unexpected error parsing date '{date_input}': {e}")
        return None


# Thread-safe session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Thread-local storage for database sessions
thread_local_data = threading.local()

# Global locks for thread-safe statistics tracking
stats_lock = threading.Lock()
progress_lock = threading.Lock()


def get_thread_db_session():
    """Get a thread-local database session"""
    if not hasattr(thread_local_data, "session"):
        thread_local_data.session = SessionLocal()
    return thread_local_data.session


def close_thread_db_session():
    """Close the thread-local database session"""
    if hasattr(thread_local_data, "session"):
        thread_local_data.session.close()
        delattr(thread_local_data, "session")


def process_single_row(
    row_data: Dict[str, Any],
    upload_task_id: int,
    available_topics: List[str],
    available_departments: List[str],
) -> Dict[str, Any]:
    """
    Process a single row in a separate thread.
    Updates statistics directly with thread-safe locks.
    Returns a dictionary with processing results.
    """
    try:
        db = get_thread_db_session()
        index = row_data["index"]
        row = row_data["row"]

        result = {"index": index, "success": False, "error": None}

        store_id = row["store_key"]  # store_key == store_id
        comment = row["answer"]  # comment == answer
        reported_at = row["submitdate"]  # reported_at == submitdate

        # Check if the store_id (store_key) is valid
        # Check if the store_id is empty
        if not store_id:
            logger.warning(f"Row {index + 1}: Store ID is empty, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Store ID is required",
            )
            db.add(error)
            db.commit()
            result["error"] = "Store ID is required"
            return result
        # Check if the store_id is in the database
        store = db.query(Store).filter(Store.id == int(store_id)).first()
        if not store:
            logger.warning(
                f"Row {index + 1}: Store ID {store_id} not found in database, skipping row"
            )
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Store ID is not valid",
            )
            db.add(error)
            db.commit()
            result["error"] = "Store ID is not valid"
            return result

        # Check if the comment is valid
        # Check if the comment is empty
        if not comment:
            logger.warning(f"Row {index + 1}: Comment is empty, skipping row")
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Comment is required",
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
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Reported at is required",
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
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=str(reported_at),
                error_message=f"Could not parse date format: {reported_at}",
            )
            db.add(error)
            db.commit()
            result["error"] = f"Could not parse date format: {reported_at}"
            return result

        reported_at = parsed_date
        # Topic (Survey sentiment, topics, departments, keywords)
        try:
            # Use synchronous extract_total in thread pool
            from utils.llm.extract_total import _extract_total_sync

            total, usage = _extract_total_sync(comment)

            # Update usage statistics atomically
            if usage:
                with stats_lock:
                    upload_task = (
                        db.query(UploadTask)
                        .filter(UploadTask.id == upload_task_id)
                        .first()
                    )
                    if upload_task:
                        upload_task.completion_tokens += usage.get(
                            "completion_tokens", 0
                        )
                        upload_task.prompt_tokens += usage.get("prompt_tokens", 0)
                        upload_task.total_tokens += usage.get("total_tokens", 0)
                        db.commit()

            # if total.cannot_classified is True, then skip the row
            if total.cannot_classified:
                error = UploadTaskError(
                    upload_task_id=upload_task_id,
                    input_store_id=store_id,
                    input_comment=comment,
                    input_reported_at=reported_at,
                    error_message="Cannot classified in AI Analysis" + str(total),
                )
                db.add(error)
                db.commit()
                result["error"] = "Cannot classified in AI Analysis"
                return result
            # Check if the topics are valid
            for topic in total.topics:
                if topic.text not in available_topics:
                    logger.warning(
                        f"Row {index + 1}: Topic {topic.text} is not valid, skipping row"
                    )
                    # Create an error for the upload task
                    error = UploadTaskError(
                        upload_task_id=upload_task_id,
                        input_store_id=store_id,
                        input_comment=comment,
                        input_reported_at=reported_at,
                        error_message=f"Topic {topic.text} is not valid",
                    )
                    db.add(error)
                    db.commit()
                    result["error"] = f"Topic {topic.text} is not valid"
                    return result
            # Check if the departments are valid
            for department in total.departments:
                if department.text not in available_departments:
                    logger.warning(
                        f"Row {index + 1}: Department {department.text} is not valid, skipping row"
                    )
                    # Create an error for the upload task
                    error = UploadTaskError(
                        upload_task_id=upload_task_id,
                        input_store_id=store_id,
                        input_comment=comment,
                        input_reported_at=reported_at,
                        error_message=f"Department {department.text} is not valid",
                    )
                    db.add(error)
                    db.commit()
                    result["error"] = f"Department {department.text} is not valid"
                    return result

        except Exception as e:
            logger.error(
                f"Row {index + 1}: Failed to extract topics and sentiment. Error: {e}"
            )
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message=f"Error conducting AI Analysis for topics: {e}",
            )
            db.add(error)
            db.commit()
            result["error"] = f"Error conducting AI Analysis for topics: {e}"
            return result
        total_topics = total.topics
        total_departments = total.departments
        total_sentiment = total.overall_sentiment
        total_keywords = total.keywords

        # Create a new survey
        survey = Survey(
            store_id=store_id,
            comment=comment,
            reported_at=reported_at,
            sentiment=total_sentiment,
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
                db.query(Keyword).filter(Keyword.keyword == keyword_obj.text).first()
            )
            if not keyword:
                logger.debug(
                    f"Row {index + 1}: Creating new keyword: {keyword_obj.text}"
                )
                keyword = Keyword(keyword=keyword_obj.text)
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
                sentiment=keyword_obj.sentiment,
            )
            db.add(survey_keyword)

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
                survey_id=survey.id, topic_id=topic.id, sentiment=topic_obj.sentiment
            )
            db.add(survey_topic)

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
                sentiment=department_obj.sentiment,
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
        close_thread_db_session()


async def process_upload_task(file_path, db, upload_task_id):
    """
    Process upload task with multi-threading support.
    Uses ThreadPoolExecutor to process multiple rows concurrently.
    """
    # Get the available topics and departments from the database
    topics = db.query(Topic).all()
    available_topics = [topic.topic for topic in topics]
    departments = db.query(Department).all()
    available_departments = [department.name for department in departments]

    # Read the file from csv file
    df = pd.read_csv(file_path)

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

    # Process rows in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_row = {
            executor.submit(
                process_single_row,
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

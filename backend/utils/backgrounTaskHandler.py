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
from datetime import datetime
from utils.llm import (
    extract_sentiment,
    extract_keywords,
    extract_topics,
    extract_department,
)

async def process_upload_task(file_path, db, upload_task_id):
    # Read the file
    df = pd.read_excel(file_path)
    for index, row in df.iterrows():
        # Check if the store_id is valid
        store_id = row["store_id"]
        comment = row["comment"]
        reported_at = row["reported_at"]
        cls_score = row["cls_score"]
        # Check if the store_id is empty
        if not store_id:
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
            continue
        # Check if the store_id is in the database
        store = db.query(Store).filter(Store.id == int(store_id)).first()
        if not store:
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
            continue
        # Check if the comment is valid
        # Check if the comment is empty
        if not comment:
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
            continue
        # Check if the reported_at is valid
        # Check if the reported_at is empty
        if not reported_at:
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
            continue
        # Check if the reported_at is a valid date
        try:
            # Convert pandas Timestamp to string first if needed
            if isinstance(reported_at, pd.Timestamp):
                reported_at = reported_at.strftime("%Y-%m-%d %H:%M:%S")
            reported_at = datetime.strptime(reported_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message="Reported at is not a valid date",
            )
            db.add(error)
            db.commit()
            continue

        # Conduct the AI Analysis (For Sentiment, Keywords, Topics, Departments)
        # Department
        try:
            department_name, usage = await extract_department(comment)
            upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            upload_task.completion_tokens += usage["completion_tokens"]
            upload_task.prompt_tokens += usage["prompt_tokens"]
            upload_task.total_tokens += usage["total_tokens"]
            upload_task.cached_tokens += usage["prompt_tokens_details"]["cached_tokens"]
            db.commit()
            db.refresh(upload_task)
            if not department_name:
                error = UploadTaskError(
                    upload_task_id=upload_task_id,
                    input_store_id=store_id,
                    input_comment=comment,
                    input_reported_at=reported_at,
                    error_message="No department found",
                )
                db.add(error)
                db.commit()
                continue
            
            # Look up the department by name
            department = db.query(Department).filter(Department.name == department_name).first()
            if not department:
                error = UploadTaskError(
                    upload_task_id=upload_task_id,
                    input_store_id=store_id,
                    input_comment=comment,
                    input_reported_at=reported_at,
                    error_message=f"Department '{department_name}' not found in database",
                )
                db.add(error)
                db.commit()
                continue
        except Exception as e:
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message=f"Error conducting AI Analysis for departments: {e}",
            )
            db.add(error)
            db.commit()
            continue
        # Sentiment
        try:
            sentiment, usage = await extract_sentiment(comment)
            upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            upload_task.completion_tokens += usage["completion_tokens"]
            upload_task.prompt_tokens += usage["prompt_tokens"]
            upload_task.total_tokens += usage["total_tokens"]
            upload_task.cached_tokens += usage["prompt_tokens_details"]["cached_tokens"]
            db.commit()
            db.refresh(upload_task)
        except Exception as e:
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message=f"Error conducting AI Analysis for sentiment: {e}",
            )
            db.add(error)
            db.commit()
            continue
        # Keywords
        try:
            keywords, usage = await extract_keywords(comment)
            upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            upload_task.completion_tokens += usage["completion_tokens"]
            upload_task.prompt_tokens += usage["prompt_tokens"]
            upload_task.total_tokens += usage["total_tokens"]
            upload_task.cached_tokens += usage["prompt_tokens_details"]["cached_tokens"]
            db.commit()
            db.refresh(upload_task)
        except Exception as e:
            # Create an error for the upload task
            error = UploadTaskError(
                upload_task_id=upload_task_id,  
                input_store_id=store_id,
                input_comment=comment,
                input_reported_at=reported_at,
                error_message=f"Error conducting AI Analysis for keywords: {e}",
            )
            db.add(error)
            db.commit()
            continue
        # Topics
        try:
            topics, usage = await extract_topics(comment)
            upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
            upload_task.completion_tokens += usage["completion_tokens"]
            upload_task.prompt_tokens += usage["prompt_tokens"]
            upload_task.total_tokens += usage["total_tokens"]
            upload_task.cached_tokens += usage["prompt_tokens_details"]["cached_tokens"]
            db.commit()
            db.refresh(upload_task)
        except Exception as e:
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
            continue
        # CLS score
        if cls_score is not None:
            cls_score = float(cls_score)
        else:
            cls_score = None
        
        # Create a new survey
        survey = Survey(
            store_id=store_id,
            comment=comment,
            reported_at=reported_at,
            sentiment=sentiment,
            department=department,
            cls_score=cls_score,
        )
        db.add(survey)
        db.commit()
        db.refresh(survey)

        # Add keywords
        for keyword_text in keywords:
            # Get or create keyword
            keyword = db.query(Keyword).filter(Keyword.keyword == keyword_text).first()
            if not keyword:
                keyword = Keyword(keyword=keyword_text)
                db.add(keyword)
                db.commit()
                db.refresh(keyword)
            
            # Create survey-keyword relationship
            survey_keyword = SurveyKeywords(survey_id=survey.id, keyword_id=keyword.id)
            db.add(survey_keyword)
        
        # Add topics
        for topic_text in topics:
            # Get or create topic
            topic = db.query(Topic).filter(Topic.topic == topic_text).first()
            if not topic:
                topic = Topic(topic=topic_text)
                db.add(topic)
                db.commit()
                db.refresh(topic)
            
            # Create survey-topic relationship
            survey_topic = SurveyTopics(survey_id=survey.id, topic_id=topic.id)
            db.add(survey_topic)
        
        db.commit()
        upload_task = (
            db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
        )
        upload_task.processed_rows += 1
        db.commit()
    # Update the upload task status
    upload_task = db.query(UploadTask).filter(UploadTask.id == upload_task_id).first()
    upload_task.status = "completed"
    db.commit()

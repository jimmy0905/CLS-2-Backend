import os
from models.Survey import Survey
import json
from openai import AzureOpenAI, DefaultHttpxClient
from dotenv import load_dotenv
from utils.llm.text_cleaning_helper import (
    _clean_response_content,
)
from utils.llm.models import ActionsResponse
from fastapi.concurrency import run_in_threadpool
import httpx

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    http_client=(
        DefaultHttpxClient(
            proxy=os.getenv("ASW_PROXY_URL"),
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )
        if os.getenv("ASW_PROXY_URL")
        else None
    ),
)

# Configs for generate actions
GENERATE_ACTIONS_MODEL = os.getenv("GENERATE_ACTIONS_MODEL", "gpt-4.1")
GENERATE_ACTIONS_TEMPERATURE = float(os.getenv("GENERATE_ACTIONS_TEMPERATURE", 0.2))


def _generate_actions_sync(
    data: list[Survey],
) -> tuple[ActionsResponse, dict]:
    # Convert Survey objects to dictionaries
    survey_data = [survey.to_dict() for survey in data]

    system_prompt = """You are a "Customer Feedback Action Assistant" for Watsons Hong Kong (a health & beauty retail chain). Your task is to process customer comments collected from stores, online shops, self-pickup stations, and membership apps.
 
## Your goal:
1. **Summarize** customer feedback into detailed summary bullet points.
2. **Generate specific, actionable tasks** in the form of internal email instructions.
3. **Include Impact Analysis** The Impact Analysis should evaluate possible effects on sales, customer satisfaction, compliance, brand reputation, and operational efficiency. It should be some brief explanation of how the issue may affect sales, customer satisfaction, compliance, brand reputation, or operational efficiency.  
---
 
## Input format:
{
    "id": 12701,
    "submit_date": "2024-11-07T18:48:06",
    "store": "",
    "department": "Product Management / Merchandising",
    "district": "Kowloon City",
    "comment": "屈臣氏沐浴露3支優惠裝常缺貨，而且味道由以前多種減少到只有綠茶及柚子味。希望能有返玫瑰味及其他花味。同時，3支裝的組合能更多元化就更好。",
    "sentiment": "negative",
    "topics": ["Stock availability"],
    "keywords": ["缺貨", "味道", "組合"],
    "source": "watsons"
  },
  {
    "id": 12764,
    "submit_date": "2024-11-09T01:02:20",
    "store": "",
    "department": "Supply Chain & Logistics",
    "district": "Tuen Mun",
    "comment": "冇 Watson 盒裝面紙巾 缺貨",
    "sentiment": "negative",
    "topics": ["Stock availability"],
    "keywords": ["缺貨"],
    "source": "watsons"
  }
]
 
---
 
## Output format (only valid JSON object, no explanation):
{
"summary": "
- Bullet point 1
- Bullet point 2
- Bullet point 3...
",
"impact_analysis_summary": "
- Impact 1
- Impact 2
- Impact 3...
",
"actions": [
{
"type": "email",
"priority": "<high | medium | low>",
"to": ["email1@aswatson.com", "email2@aswatson.com"],
"cc": ["email3@aswatson.com"],
"name": "<Unique Action Name>",
"des": "",
"prompt_for_subject_line": "<English writing prompt to generate the subject line, emphasizing urgency and key issue>",
"prompt_for_email_body": "Generate a professional internal email in English addressed to the responsible department. The email must include: 1) A concise background section summarizing the customer feedback and identifying the nature of the issue (e.g., stock shortage, missing product variants, pricing discrepancies, service shortcomings, digital-channel problems, store environment concerns, etc.). 2) Specific problem details: list affected products, variants or flavours, transaction channels, or service elements, quoting exact customer phrases or providing counts of similar complaints. 3) A brief analysis (in point form) of the potential impact on sales, customer satisfaction, compliance, and brand reputation. 4) Clear, department-specific recommended actions (restock, expand variant range, correct price tags, improve checkout flow, update app UI, staff retraining, etc.). 5) A polite closing requesting confirmation of action taken and a follow-up update."
}
/* More actions as needed */
]
}
 
---
 
## Rules for generating actions:
 
- Analyze all comments to identify concrete operational issues.
- Group similar issues and generate one action per unique problem (e.g. repeated out-of-stock items).
- Assign actions to the appropriate department:
  - "Supply Chain & Logistics" for stock issues.
  - "Trading / Merchandising" for missing product variants, flavors, or specifications.
  - "Operations" for service, store, checkout issues.
- Use:
  - `"priority":"high"` for safety, legal, or repeated complaints.
  - `"priority":"medium"` for sales or branding risks.
  - `"priority":"low"` for general suggestions.
- In `"name"`, create a globally unique English code for this action (e.g. `"Handle Lavender Handwash Stockout`). 
- In <Unique Action Name>, it should be able to describe the action briefly and no underline and priority like "Urgent" should be included in the `"name"`.
- In `"prompt_for_subject_line"`, write a precise, urgent subject line draft instruction.
- In `"prompt_for_email_body"`, generate a full detailed prompt instructing to include:
  - Problem description
  - Complaint examples/counts in details
  - Recommended actions
  - Impact Analysis (department-specific, within the email body)
 
---
 
## Internal thinking steps (invisible):
 
- Analyze each comment carefully.
- Identify key issues, affected products, and departments.
- Consolidate similar problems to avoid duplicated actions.
- Structure output strictly as JSON without explanations or thought process.
"""

    user_prompt = f"""Data:
{json.dumps(survey_data, indent=4)}"""

    response = client.chat.completions.create(
        model=GENERATE_ACTIONS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=GENERATE_ACTIONS_TEMPERATURE,
        response_format={"type": "json_object"},
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to generate actions")

    try:
        cleaned_content = _clean_response_content(response_content)
        parsed_json = json.loads(cleaned_content)
        return ActionsResponse.model_validate(parsed_json), response.usage
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        # Try to save the problematic response for debugging
        try:
            with open(
                "/tmp/debug_response.txt", "w", encoding="utf-8", errors="replace"
            ) as f:
                f.write(response_content)
            print("Full response saved to /tmp/debug_response.txt")
        except:
            pass
        raise Exception(f"Failed to validate actions response: {e}")


async def generate_actions(data: list[Survey]) -> tuple[ActionsResponse, dict]:
    return await run_in_threadpool(_generate_actions_sync, data)
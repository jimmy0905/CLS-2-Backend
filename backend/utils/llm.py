from openai import AzureOpenAI
import json
import os
import re
from dotenv import load_dotenv
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from models.Survey import Survey


load_dotenv()

# Helper to ensure JSON strings do not contain raw newlines
# Raw line-feed characters within quoted JSON values are invalid and cause
# ``json.loads`` to raise ``JSONDecodeError``.  This function replaces those
# newlines with the escaped sequence ``\n`` _only_ inside string literals so
# that the overall structure of the JSON remains unchanged.

def _escape_newlines_in_json_strings(content: str) -> str:
    """Escape unescaped newline characters appearing inside JSON string values."""
    string_pattern = re.compile(r'"(?:[^"\\]|\\.)*"', re.DOTALL)

    def _replace(match: re.Match) -> str:
        # Within a JSON string literal, replace raw LF with the escaped version
        return match.group(0).replace("\n", "\\n")

    return string_pattern.sub(_replace, content)


def _strip_markdown_code_blocks(content: str) -> str:
    """Strip markdown code block formatting from response content."""
    if not content:
        return content
    
    content = content.strip()
    
    # Remove ```json...``` or ```...``` code block markers
    if content.startswith('```json'):
        content = content[7:]  # Remove ```json
    elif content.startswith('```'):
        content = content[3:]   # Remove ```
    
    if content.endswith('```'):
        content = content[:-3]  # Remove trailing ```
    
    return content.strip()


def _clean_response_content(response_content: str) -> str:
    """Clean control characters and other problematic characters from OpenAI API response content."""
    if response_content is None:
        return ""
    
    # First, strip markdown code blocks
    cleaned_content = _strip_markdown_code_blocks(response_content)
    
    # Then, normalize newlines and remove any BOM or null bytes
    cleaned_content = cleaned_content.replace('\r\n', '\n').replace('\r', '\n')
    cleaned_content = cleaned_content.replace('\x00', '').replace('\ufeff', '')
    
    try:
        # Try to parse the JSON first
        parsed = json.loads(cleaned_content)
        
        # For string values in the JSON, clean any remaining control characters
        def clean_strings(obj):
            if isinstance(obj, str):
                # Remove control characters except newlines
                return re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', obj)
            elif isinstance(obj, dict):
                return {k: clean_strings(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_strings(item) for item in obj]
            return obj
        
        # Clean all string values in the JSON
        cleaned_parsed = clean_strings(parsed)
        
        # Re-serialize with ensure_ascii=False to maintain Unicode characters
        return json.dumps(cleaned_parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        # If JSON parsing fails, clean the entire content as a string
        cleaned_content = re.sub(r'[\x00-\x09\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', cleaned_content)
        
        # NEW: escape raw newlines that appear inside JSON string values so that the
        # JSON becomes parseable by the standard library
        cleaned_content = _escape_newlines_in_json_strings(cleaned_content)

        try:
            # Try parsing one more time after cleaning
            parsed = json.loads(cleaned_content)
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            # If still failing, return the cleaned content as-is
            return cleaned_content


client = AzureOpenAI(
    api_key=os.getenv(
        "AZURE_OPENAI_API_KEY",
        "",
    ),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-07-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
)
# Configs for extract keywords
EXTRACT_KEYWORDS_MODEL = os.getenv("EXTRACT_KEYWORDS_MODEL", "gpt-4.1-mini")
EXTRACT_KEYWORDS_TEMPERATURE = float(os.getenv("EXTRACT_KEYWORDS_TEMPERATURE", 0.0))

# Configs for extract topics
EXTRACT_TOPICS_MODEL = os.getenv("EXTRACT_TOPICS_MODEL", "gpt-4.1-mini")
EXTRACT_TOPICS_TEMPERATURE = float(os.getenv("EXTRACT_TOPICS_TEMPERATURE", 0.0))

# Configs for extract departments
EXTRACT_DEPARTMENTS_MODEL = os.getenv("EXTRACT_DEPARTMENTS_MODEL", "gpt-4.1-mini")
EXTRACT_DEPARTMENTS_TEMPERATURE = float(
    os.getenv("EXTRACT_DEPARTMENTS_TEMPERATURE", 0.0)
)

# Configs for extract sentiment
EXTRACT_SENTIMENT_MODEL = os.getenv("EXTRACT_SENTIMENT_MODEL", "gpt-4.1-mini")
EXTRACT_SENTIMENT_TEMPERATURE = float(os.getenv("EXTRACT_SENTIMENT_TEMPERATURE", 0.0))

# Configs for generate actions
GENERATE_ACTIONS_MODEL = os.getenv("GENERATE_ACTIONS_MODEL", "gpt-4.1")
GENERATE_ACTIONS_TEMPERATURE = float(os.getenv("GENERATE_ACTIONS_TEMPERATURE", 0.2))

# Configs for generate email
GENERATE_EMAILS_MODEL = os.getenv("GENERATE_EMAILS_MODEL", "gpt-4.1")
GENERATE_EMAILS_TEMPERATURE = float(os.getenv("GENERATE_EMAILS_TEMPERATURE", 0.25))
GENERATE_EMAILS_MAX_TOKENS = int(os.getenv("GENERATE_EMAILS_MAX_TOKENS", 10000))

# Configs for generate strategy
GENERATE_STRATEGY_MODEL = os.getenv("GENERATE_STRATEGY_MODEL", "gpt-4.1")
GENERATE_STRATEGY_TEMPERATURE = float(os.getenv("GENERATE_STRATEGY_TEMPERATURE", 0.25))
GENERATE_STRATEGY_MAX_TOKENS = int(os.getenv("GENERATE_STRATEGY_MAX_TOKENS", 10000))

def _extract_keywords_sync(text: str) -> list[str]:
    system_prompt = """You are an AI assistant specialized in analyzing retail customer feedback. Your task is to extract 1 to 3 most important keywords from the comments. These keywords should focus on areas such as product quality, IT, customer service, pricing, and overall shopping experience or anything related to retails."""
    user_prompt = f"""Extract 1 to 3 most important keywords from the following customer comment. Make sure the words should be exactly the same as in the comment. Output only JSON with key \"keywords\":\n\n"{text}"\n"""

    response = client.chat.completions.create(
        model=EXTRACT_KEYWORDS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_KEYWORDS_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return []
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return json.loads(cleaned_response_content)["keywords"]
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response: {e}")


def _extract_topics_sync(text: str) -> list[str]:
    system_prompt = """You are an AI assistant specialized in analyzing retail customer feedback. Your task is to extract 2 to 3 primary keywords that capture the essential topics of the customer comment. These keywords should focus on areas such as product quality, IT, customer service, pricing, and overall shopping experience."""
    user_prompt = f"""Extract 2 to 3 keywords from the following customer comment that best summarize its main points.All the output should be in English. Output only JSON with key \"keywords\":\n\n"{text}"\n"""

    response = client.chat.completions.create(
        model=EXTRACT_TOPICS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_TOPICS_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return []
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return json.loads(cleaned_response_content)["keywords"]
    except Exception as e:
        print(f"Error validating topics JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate topics response: {e}")


def _extract_department_sync(text: str) -> str:
    system_prompt = """You are a highly capable AI assistant specializing in categorizing retail customer feedback. 
You will be given a single customer comment, and your task is to identify which department(s) 
within a retail organization should address that comment.

Here are the possible departments and their typical responsibilities:

1. Customer Service
   - Handles general inquiries, complaints, returns, refunds, and escalations.

2. Operations / Store Management
   - Manages in-store experience, cleanliness, staff conduct, and day-to-day operations.

3. IT Department
   - Addresses technical issues such as website errors, app glitches, and system malfunctions.

4. Marketing & Communications
   - Oversees promotions, advertising campaigns, brand perception, and customer engagement efforts.

5. Product Management / Merchandising
   - Manages product lines, pricing, availability, and quality feedback.

6. Supply Chain & Logistics
   - Deals with delivery delays, shipping errors, and stock management problems.

7. Quality Assurance
   - Focuses on product/service standards, defect investigations, and improvements.

8. Finance & Billing
   - Handles billing errors, payment disputes, refund policies, and financial documentation.

9. Human Resources
   - Involved in staff behavior, performance issues, training needs, and internal policy adherence.

10. Legal & Compliance
    - Manages regulatory, legal, and compliance-related matters, including data privacy and consumer rights.

11. E-commerce & Digital Experience
    - Responsible for the online shopping platform, checkout process, website/app usability, 
      and digital marketing efforts.

Instructions:
- Read the customer comment carefully.
- Determine the most relevant department(s) based on the content of the comment.
- If multiple departments are equally relevant, only return the first one.
- Output your final classification in JSON format under the key "departments" as an array of strings.
- Do not include additional commentary or explanation in the output.

Example output format:
{
  "departments": ["IT Department"]
}
"""
    user_prompt = f"""Classify the following customer comment into the most relevant department(s). 
    Remember to output in JSON under the key "departments" only:

    "{text}"
    """
    response = client.chat.completions.create(
        model=EXTRACT_DEPARTMENTS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_DEPARTMENTS_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return ""
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return json.loads(cleaned_response_content)["departments"][0]
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate departments response: {e}")


def _extract_sentiment_sync(text: str) -> str:
    system_prompt = """You are a highly capable AI assistant specializing in sentiment analysis of retail customer feedback.
You will be given a single customer comment, and your task is to analyze its sentiment.

For each comment, provide only:

Overall Sentiment: Classify as one of the following:
   - Positive
   - Neutral
   - Negative

Instructions:
- Read the customer comment carefully.
- Analyze both the explicit and implicit sentiment.
- Consider cultural context and nuanced language.
- Output your final analysis in JSON format with ONLY the sentiment field.
- Do not include additional commentary or explanation in the output.

Example output format:
{
  "sentiment": "Positive"
}
"""

    user_prompt = f"""Analyze the sentiment of the following customer comment. 
Remember to output in JSON format with ONLY the sentiment field:

"{text}"
"""

    response = client.chat.completions.create(
        model=EXTRACT_SENTIMENT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_SENTIMENT_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return ""
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return json.loads(cleaned_response_content)["sentiment"]
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate sentiment response: {e}")


class Action(BaseModel):
    type: str
    priority: str
    to: list[str]
    cc: list[str]
    name: str
    des: str
    prompt_for_subject_line: str
    prompt_for_email_body: str


class ActionsResponse(BaseModel):
    summary: str
    actions: list[Action]


def _generate_actions_sync(
    data: list[Survey],
) -> ActionsResponse:
    # Convert Survey objects to dictionaries
    survey_data = [survey.to_dict() for survey in data]

    system_prompt = """You are a "Customer Feedback Action Assistant" for Watsons Hong Kong (a health & beauty retail chain). Your task is to process customer comments collected from stores, online shops, self-pickup stations, and membership apps.

## Your goal:
1. **Summarize** customer feedback into a concise bullet points with some critical details.
2. **Generate specific, actionable tasks** in the form of internal email instructions.

---

## Input format:
{
    "id": 1472,
    "store": {
      "id": 3498,
      "name": "Lohas",
      "district": {
        "id": 14,
        "name": "Sai Kung"
      },
      "source": {
        "id": 1,
        "name": "Watsons"
      }
    },
    "department": {
      "id": 1,
      "name": "Operations / Store Management"
    },
    "comment": "貨品擺放好亂，周圍太多什物",
    "sentiment": "Negative",
    "reported_at": "2024-11-30T15:24:09",
    "created_at": "2025-07-28T06:46:09.654512",
    "updated_at": "2025-07-28T06:46:09.654512",
    "topics": [
      "shopping experience",
      "product placement",
      "store organization"
    ],
    "keywords": [
      "貨品",
      "擺放",
      "亂"
    ]
  },
  {
    "id": 1317,
    "store": {
      "id": 3247,
      "name": "The Southside",
      "district": {
        "id": 5,
        "name": "Southern"
      },
      "source": {
        "id": 1,
        "name": "Watsons"
      }
    },
    "department": {
      "id": 4,
      "name": "Human Resources"
    },
    "comment": "店員Sunny鳳，望客人既眼神，令人感到有敵意",
    "sentiment": "Negative",
    "reported_at": "2024-11-27T13:23:29",
    "created_at": "2025-07-28T06:46:07.288636",
    "updated_at": "2025-07-28T06:46:07.288636",
    "topics": [
      "customer service",
      "staff behavior",
      "hostility"
    ],
    "keywords": [
      "店員",
      "眼神",
      "敵意"
    ]
  }



---

## Output format (only valid JSON object, no explanation):
{
"summary": "
- Bullet point 1
- Bullet point 2
- Bullet point 3...
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
"prompt_for_email_body": "Generate a professional internal email in English addressed to the responsible department. The email must include: 1) A concise background section summarizing the customer feedback and identifying the nature of the issue (e.g., stock shortage, missing product variants, pricing discrepancies, service shortcomings, digital‑channel problems, store environment concerns, etc.). 2) Specific problem details: list affected products, variants or flavours, transaction channels, or service elements, quoting exact customer phrases or providing counts of similar complaints. 3) An brief analysis (in oint form) of the potential impact on sales, customer satisfaction, compliance, and brand reputation. 4) Clear, department‑specific recommended actions (restock, expand variant range, correct price tags, improve checkout flow, update app UI, staff retraining, etc.). 5) A polite closing requesting confirmation of action taken and a follow‑up update."
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

---

## Internal thinking steps (invisible):

- Analyze each comment carefully.
- Identify key issues, affected products, and departments.
- Consolidate similar problems to avoid duplicated actions.
- Structure output strictly as JSON without explanations or thought process."""

    user_prompt = f"""Data:
{json.dumps(survey_data, indent=4)}"""

    response = client.chat.completions.create(
        model=GENERATE_ACTIONS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=GENERATE_ACTIONS_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to generate actions")
    
    try: 
        cleaned_content = _clean_response_content(response_content)
        parsed_json = json.loads(cleaned_content)
        
        # Finally validate with Pydantic
        return ActionsResponse.model_validate(parsed_json)
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        # Try to save the problematic response for debugging
        try:
            with open('/tmp/debug_response.txt', 'w', encoding='utf-8', errors='replace') as f:
                f.write(response_content)
            print("Full response saved to /tmp/debug_response.txt")
        except:
            pass
        raise Exception(f"Failed to validate actions response: {e}")


class EmailData(BaseModel):
    summary: str
    action: Action
    survey_data: list[dict]


class EmailResponse(BaseModel):
    subject_line: str
    email_body: str


def _generate_email_sync(data: EmailData) -> EmailResponse:
    system_prompt = """Role:  
You are “WatsonsHongKong Internal Email Composer.”  Your sole task is to transform the user-supplied prompt—containing customer-feedback details, recommended actions, and deadlines—into a polished internal email body in English.

Output requirements  
1. Produce **only** the email body text (no subject line, no metadata).  
2. Follow this structure:
   • Greeting to the responsible department or team (e.g., “Dear Trading Team,”).  
   • **Background** - one concise paragraph summarising the customer feedback and clearly stating the type of issue. Potential issue types include, but are not limited to:  
     - Stock shortage / stockout  
     - Missing product variants or flavours  
     - Pricing discrepancies or promotions errors  
     - Service shortcomings (staff attitude, checkout delays, etc.)  
     - Digital-channel problems (app / website UX, payment failures, click-and-collect issues)  
     - Store environment concerns (cleanliness, layout, shelf signage, lighting)  
   • **Problem Details (in detailed point form)** - explicit description of affected products, variants/flavours, channels, or service elements. Quote key customer phrases **or** state complaint counts where available.  
   • **Impact Analysis** - brief explanation of how the issue may affect sales, customer satisfaction, compliance, brand reputation, or operational efficiency.
   • **Recommended Actions** - clear, department-specific steps (e.g., replenish stock, introduce sakura & lavender variants, correct price tags, retrain staff, fix checkout flow, update app UI). Use a numbered or bulleted list.  
   • **Closing** - polite request for confirmation of next steps or resolution, plus thanks.  
   • Signature placeholder:  
     ```
     Best regards,
     [Your Name]
     Customer Feedback Action Assistant
     ```

3. **Include every detail provided in the user prompt**—product names, missing variants, prices, store locations, complaint counts, deadlines, etc. Do **not** invent new data or omit any given information.  
4. Maintain clarity, professionalism, and conciseness; avoid jargon and repetition.  
5. Return **only** a valid JSON object with both "subject_line" and "email_body" fields—no additional commentary.

---

## Input format:
{
    "summary": "",
    "action": 
    {
        "type": "email",
        "priority": "<high | medium | low>",
        "to": ["email1@aswatson.com", "email2@aswatson.com"],
        "cc": ["email3@aswatson.com"],
        "name": "<unique_action_name>",
        "des": "",
        "prompt_for_subject_line": "<English writing prompt to generate the subject line, emphasizing urgency and key issue>",
        "prompt_for_email_body": "Generate a professional internal email in English addressed to the responsible department. The email must include: 1) A concise background section summarizing the customer feedback and identifying the nature of the issue (e.g., stock shortage, missing product variants, pricing discrepancies, service shortcomings, digital‑channel problems, store environment concerns, etc.). 2) Specific problem details: list affected products, variants or flavours, transaction channels, or service elements, quoting exact customer phrases or providing counts of similar complaints. 3) An brief analysis (in oint form) of the potential impact on sales, customer satisfaction, compliance, and brand reputation. 4) Clear, department‑specific recommended actions (restock, expand variant range, correct price tags, improve checkout flow, update app UI, staff retraining, etc.). 5) A polite closing requesting confirmation of action taken and a follow‑up update."
    },
    "survey_data": [
    {
        "id": 12764,
        "submit_date": "2024-11-09T01:02:20",
        "store": "",
        "department": "Supply Chain & Logistics",
        "district": "Tuen Mun",
        "comment": "冇 Watson 盒裝面紙巾 缺貨",
        "sentiment": "Negative",
        "topics": ["Stock availability"],
        "keywords": ["缺貨"],
        "source": "watsons"
    },
    /* More survey data as needed */
    ]
}

---

## Output format (only valid JSON object, no explanation):
{
    "subject_line": "",
    "email_body": ""
}
"""
    user_prompt = f"""Data:
    {data.summary}
    {data.action}
    {json.dumps(data.survey_data, indent=4, ensure_ascii=False, default=str)}
"""
    response = client.chat.completions.create(
        model=GENERATE_EMAILS_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=GENERATE_EMAILS_TEMPERATURE,
        max_tokens=GENERATE_EMAILS_MAX_TOKENS,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to generate email")
    
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return EmailResponse.model_validate_json(cleaned_response_content)
    except Exception as e:
        print(f"Error validating email JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        # Try to save the problematic response for debugging
        try:
            with open('/tmp/debug_email_response.txt', 'w', encoding='utf-8', errors='replace') as f:
                f.write(response_content)
            print("Full response saved to /tmp/debug_email_response.txt")
        except:
            pass
        raise Exception(f"Failed to validate email response: {e}")


def _generate_strategy_sync(data: list[Survey]) -> str:
    system_prompt = """You are given a JSON array of customer comments from the Top10 Watsons 香港 stores by sentiment score. Each object has these fields: id, store, department, district, comment, sentiment, topics, keywords.

Your tasks:
1. Aggregate all comments and identify the core positive themes.
2. Using a clear chain‑of‑thought, infer the behind‑the‑scenes actions or practices that produced those themes.
3. From those inferences, formulate practical, actionable strategies any Watsons store can adopt.
5. Return **only** the final Summary and Strategy body text in markdown — no JSON,  or additional commentary.
6.  All returned content (headings, subtitles, etc.) must be in Traditional Chinese, but please 1234 for those number.  
7. Each recommendation must focus on store‑level operations, i.e. actions implementable by store staff or managers (how to serve customers, brief staff, conduct daily operations).

Input format:
```json
[
  {
    "id": 1443,
    "store": "Watsons",
    "department": "Operations / Store Management",
    "district": "Eastern",
    "comment": "店員很樂意及熱情幫助我要揾的貨品",
    "sentiment": "Positive",
    "topics": ["Staff attitude"],
    "keywords": ["店員","樂意","熱情"]
  },
  {
    "id": 2264,
    "store": "Watsons",
    "department": "Product Management / Merchandising",
    "district": "Kwun Tong",
    "comment": "多一些選擇",
    "sentiment": "Positive",
    "topics": ["Product range"],
    "keywords": ["選擇"]
  },
  {
    "id": 1517,
    "store": "Watsons",
    "department": "Human Resources",
    "district": "Southern",
    "comment": "Joey十分友善專業。",
    "sentiment": "Positive",
    "topics": ["Staff attitude"],
    "keywords": ["友善","專業"]
  }
  …（共10家店的正面評論）…
]
````

Output in Markdown format, following this template:

<Start>
# Summary<br />
- <Concise statement of key positive factors across all comments>
- …

# Strategy <br />
1. ## **<Inferred Action A>** 
   ### **Observation**:<br />
   “因為多位顧客提到『熱情』，可推斷門店定期舉辦主動迎賓及服務禮儀培訓。” 
   ### **Recommendation:** 
   - 每日開店前，由店經理進行 5 分鐘迎賓話術及服務示範。
   - 角色扮演演練：員工輪流扮演顧客，練習 5 秒內主動問候。

2. ## **<Inferred Action B>** 
   ### **Observation**:<br /> 
   “Customers request ‘多一些選擇’，so the store likely performs weekly inventory reviews.” 
   ### **Recommendation:**
   -To replicate this, schedule a weekly product‑range audit to restock and expand popular categories.
3.....
<End>


Chain‑of‑thought guidance:

* Cluster comments by recurring keywords/topics.
* For each cluster, ask: “What daily operational practice, training, or policy generates this feedback?”
* Articulate each as an “Inferred Action” with a brief chain‑of‑thought.* The Recommendation should focus on store operation level.
* Use Markdown headings (`##`), <br /> and bullets as shown.
* Observation is like the Chain‑of‑thought
* <Start> and <End> no need to show.
* Group similar actions under thematic subheadings in the Strategy section.
* For content inside the each Recommendation, please show in bullet points.

"""
    user_prompt = f"""Data:
    {json.dumps(data, indent=4, ensure_ascii=False, default=str)}
"""
    response = client.chat.completions.create(
        model=GENERATE_STRATEGY_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=GENERATE_STRATEGY_TEMPERATURE,
        max_tokens=GENERATE_STRATEGY_MAX_TOKENS,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to generate strategy")
    return response_content


async def extract_keywords(text: str) -> list[str]:
    return await run_in_threadpool(_extract_keywords_sync, text)


async def extract_topics(text: str) -> list[str]:
    return await run_in_threadpool(_extract_topics_sync, text)


async def extract_department(text: str) -> str:
    return await run_in_threadpool(_extract_department_sync, text)


async def extract_sentiment(text: str) -> str:
    return await run_in_threadpool(_extract_sentiment_sync, text)


async def generate_actions(data: list[Survey]) -> ActionsResponse:
    return await run_in_threadpool(_generate_actions_sync, data)


async def generate_email(data: EmailData) -> EmailResponse:
    return await run_in_threadpool(_generate_email_sync, data)


async def generate_strategy(data: list[Survey]) -> str:
    return await run_in_threadpool(_generate_strategy_sync, data)

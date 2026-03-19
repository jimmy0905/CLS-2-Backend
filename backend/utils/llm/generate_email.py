import os
import json
from openai import AzureOpenAI, DefaultHttpxClient
from dotenv import load_dotenv
from utils.llm.models import EmailData, EmailResponse
from utils.llm.text_cleaning_helper import _clean_response_content
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
# Configs for generate email
GENERATE_EMAILS_MODEL = os.getenv("GENERATE_EMAIL_MODEL", "gpt-4.1")
GENERATE_EMAILS_TEMPERATURE = float(os.getenv("GENERATE_EMAIL_TEMPERATURE", 0.25))
GENERATE_EMAILS_MAX_TOKENS = int(os.getenv("GENERATE_EMAIL_MAX_TOKENS", 10000))


def _generate_email_sync(data: EmailData) -> tuple[EmailResponse, dict]:
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
        "sentiment": "negative",
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
        response_format={"type": "json_object"},
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to generate email")

    try:
        cleaned_response_content = _clean_response_content(response_content)
        return (
            EmailResponse.model_validate_json(cleaned_response_content),
            response.usage,
        )
    except Exception as e:
        print(f"Error validating email JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        # Try to save the problematic response for debugging
        try:
            with open(
                "/tmp/debug_email_response.txt", "w", encoding="utf-8", errors="replace"
            ) as f:
                f.write(response_content)
            print("Full response saved to /tmp/debug_email_response.txt")
        except:
            pass
        raise Exception(f"Failed to validate email response: {e}")


async def generate_email(data: EmailData) -> tuple[EmailResponse, dict]:
    return await run_in_threadpool(_generate_email_sync, data)

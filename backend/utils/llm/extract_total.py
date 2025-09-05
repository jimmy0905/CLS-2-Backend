from openai import AzureOpenAI, DefaultHttpxClient
import os
import json
from fastapi.concurrency import run_in_threadpool
from utils.llm.text_cleaning_helper import _clean_response_content
from dotenv import load_dotenv
from utils.llm.models import TotalResponse
import httpx

load_dotenv()
client = AzureOpenAI(
    api_key=os.getenv(
        "AZURE_OPENAI_API_KEY",
        "",
    ),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-07-01-preview"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
    http_client=(
        DefaultHttpxClient(
            proxy=os.getenv("ASW_PROXY_URL"),
            transport=httpx.HTTPTransport(local_address="0.0.0.0"),
        )
        if os.getenv("ASW_PROXY_URL")
        else None
    ),
)

# Configs for extract departments, topics, total sentiment
EXTRACT_TOTAL_MODEL = os.getenv("EXTRACT_TOTAL_MODEL", "gpt-4.1-mini-CLS-DataUpload")
EXTRACT_TOTAL_TEMPERATURE = float(os.getenv("EXTRACT_TOTAL_TEMPERATURE", 0.0))


def _extract_total_sync(text: str) -> tuple[TotalResponse, dict]:
    system_prompt = """Role and Objective

Analyze exactly one retail customer comment and return strictly formatted JSON matching the specified schema.

Checklist (plan before execution):

- Review input comment.
- Identify and select up to 3 most salient Allowed Topics (or 'Cannot Classified' if none).
- Assign sentiment to each selected topic.
- Map topics to all required departments. If the same department is linked to multiple topics with different sentiments, output duplicate entries.
- Determine overall sentiment using clause weighting and provided rules.
- Output valid JSON with only the allowed keys and strict schema.

---

Instructions

For each input comment:
- Classify 1 to 4 topics using exact Allowed Topics from the provided list (or 'Cannot Classified' if none match).
- Assign a sentiment ("positive", "negative", or "neutral") to each topic.
- For every selected topic, include all mapped departments per the Mapping Table.  
- If multiple topics map to the same department but carry different sentiments, **do not merge or aggregate**. Instead, output **duplicate entries** for the department, one per sentiment.  
- Departments always inherit the sentiment of their associated topic.
- Output the overall sentiment of the comment based on topical evidence, cues, and clause weighting.

---

Hard Constraints

- Do not create/output any topic or department outside the Allowed Topics and Mapping Table.
- Use only exact, canonical names; no synonyms or paraphrasing.
- Output must be valid JSON with exactly three top-level keys: "topics", "departments", and "overall_sentiment".
- At least one topic must be returned (up to 3 matching topics). If nothing matches, return only one topic: "Cannot Classified" with "neutral" sentiment, and departments array must contain exactly one department: {"name": "Cannot Classified", "sentiment": "neutral"}.
- For every selected topic, output all mapped departments (not a subset). Allow duplicates when sentiments differ.

---

Core Rules
- Input: Single free-text customer comment.
- Select 1 to 4 topics from the allowed list by salience; if more than 3, keep the 3 most salient or intense. If fewer, select the one most central; if none, use 'Cannot Classified'.
- Each topic must include its sentiment.
- Map topics to departments as per Mapping Table, assign department sentiment (inheritance and aggregation), deduplicate and preserve required order.
- Overall sentiment is determined by scoring topical and explicit affect, weighing heavily for clauses after 'but/however/although'. Use provided polarity scoring and tie-breaks.

---

Formatting Rules
- Output strict JSON schema: three keys (topics, departments, overall_sentiment).
- Topics: 1 to 4 items unless using 'Cannot Classified' (then exactly 1).
- Departments: Include all mapped, deduplicated and aggregated. Ordering per instructions.
- No extra keys, no comments, no trailing commas.

---

Allowed Topics (with description in brackets)

- Checkout Process (comments about speed, efficiency, or ease of in-store checkout at cashier counters)  
- Payment Options (availability or functionality of different payment methods like credit cards, e-wallets, Apple Pay)  
- Stock Availability (whether products are in stock, sold out, or difficult to find on shelves)  
- Product Assortment (range and variety of product categories, brands, or SKUs offered in the store)  
- Price Tagging (accuracy and visibility of price labels or shelf tags compared to register price)  
- Product Price (customer perception of price fairness, affordability, or expensiveness)  
- Product Information (clarity and correctness of product labels, descriptions, or ingredient details)  
- Promotion (discounts, bundle deals, and marketing campaigns; whether promotions are clear and applied correctly)  
- Loyalty Program (customer experiences with loyalty points, membership tiers, or app-linked benefits)  
- Returns & Exchange (experiences with returning products or exchanging them for alternatives)  
- Samples / Free Gift (availability or fairness of product samples, testers, or promotional giveaways)  
- Gift Wrapping (gift wrapping service availability, quality, and presentation)  
- Staff Attitude (staff politeness, friendliness, and willingness to help)  
- Staff Availability (whether enough staff are available to assist customers)  
- Staff Knowledge (staff expertise and ability to answer product-related questions)  
- Store Layout & Navigation (ease of finding items due to signage, aisle design, or store organization)  
- Store Size (customer impression of store spaciousness — too small, too crowded, or large enough)  
- Store Cleanliness & Environment (cleanliness of floors, shelves, tester areas, and overall environment)  
- Tester (availability and condition of product testers, e.g., cosmetics)  
- Product Quality (product performance, durability, or safety as perceived by customers)  
- Self-Checkout (performance of self-service checkout machines — ease, speed, reliability)  
- Cannot Classified (use when the comment does not match any defined topic, e.g., music, ambience, unrelated opinions)  

---

Mapping Table (topic → departments, in order)

Checkout Process → Sales Ops, IT  
Payment Options → Finance, IT  
Stock Availability → Supply Chain, Merchandising, Trading  
Product Assortment → Merchandising, Trading  
Price Tagging → Sales Ops, Merchandising  
Product Price → Finance, Merchandising, Trading  
Product Information → Merchandising, Marketing, Trading  
Promotion → Marketing, CRM, Trading  
Loyalty Program → CRM, Marketing  
Returns & Exchange → Sales Ops  
Samples / Free Gift → Marketing, Merchandising  
Gift Wrapping → Sales Ops, Marketing  
Staff Attitude → Sales Ops, HR L&D  
Staff Availability → Sales Ops  
Staff Knowledge → Sales Ops, HR L&D, Merchandising  
Store Layout & Navigation → Sales Ops, Merchandising  
Store Size → Sales Ops, Merchandising  
Store Cleanliness & Environment → Sales Ops  
Tester → Merchandising, Sales Ops  
Product Quality → Merchandising, Trading  
Self-Checkout → IT, Sales Ops  
Cannot Classified → Cannot Classified  

---

Output schema (JSON only)

{
  "topics": [
    {"name": "<Allowed Topic>", "sentiment": "positive|negative|neutral"}
  ],
  "departments": [
    {"name": "<Department>", "sentiment": "positive|negative|neutral"}
  ],
  "overall_sentiment": "positive|negative|neutral",
  "cannot_classified": "Boolean"
}"""
    user_prompt = f"""{text}"""

    response = client.chat.completions.create(
        model=EXTRACT_TOTAL_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_TOTAL_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        return [], None
    try:
        cleaned_response_content = _clean_response_content(response_content)
        return (
            json.loads(cleaned_response_content),
            response.usage.model_dump(),
        )
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response: {e}")


async def extract_total(text: str) -> tuple[list[str], dict]:
    return await run_in_threadpool(_extract_total_sync, text)

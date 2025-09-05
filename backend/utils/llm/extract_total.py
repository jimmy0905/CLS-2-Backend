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
Role and Objective
You are an AI assistant analyzing exactly one retail customer comment.  
Your task is to classify topics, departments, and keywords with sentiment, and return a strictly formatted JSON.  
If no valid topic can be classified, return only: {"cannot_classified": true}.  

---

Instructions
1. Read the input comment carefully.  
2. Identify 1–4 most salient Allowed Topics (or "Cannot Classified" if none).  
   - Allow duplicate topics ONLY when the same topic has different sentiments. If multiple mentions yield the same topic with the same sentiment, COLLAPSE into a single topic entry. 
3. Assign sentiment ("positive", "negative", "neutral") to each topic.  
4. Map topics to ALL departments from the Mapping Table.  
   - Each department inherits sentiment from its **source topic**.  
   - If multiple topics map to the same department with different sentiments, include duplicates (do not merge).  
   - If multiple mappings produce the SAME (department, sentiment), COLLAPSE to a single department entry.
5. Extract 1–3 **keywords** from the comment.  
   - Keywords must be **exact substrings from the comment** (not paraphrased, no full sentences).  
   - Keep them short: 1–3 words, maximum 4.  
   - Keywords must be **the minimal meaningful unit** (e.g., "優惠券", "自家品牌", "易賞錢app"), not full phrases or sentences.  
   - Numbers, lengthy conditions, or entire clauses are not allowed.  
   - Each keyword inherits sentiment from its **source department**.  
   - **Duplication allowed**: if the same keyword occurs in different contexts with different sentiments, include multiple entries (do not merge).  
   - If multiple occurrences yield the SAME (keyword text, sentiment), COLLAPSE to a single keyword entry.
6. Compute overall sentiment of the entire comment (positive, negative, neutral) using clause weighting.  
7. If no valid topic exists: return only {"cannot_classified": true}.  

---

Core Rules
- Topics: must be chosen only from the Allowed Topics list.  
- At least 1 and up to 4 topics must be returned if classification succeeds.  
- "Cannot Classified" is only used if no valid topic is found.  
- Departments: must follow Mapping Table exactly.  All the Departments mapped with topics must be included.
- Duplication allowed: topics, departments, and keywords may appear multiple times if linked to different sentiments.  
- Keywords: must be exact substrings from the comment, **short spans only**, inherit sentiment.  
- Although the output does not include "source" fields, internally you must use the concept of **source topic → source department → keyword** to maintain consistency.  
- Overall sentiment: based on topical evidence and cues (e.g., polarity after “but/however” has higher weight).  
- If cannot classify: return only {"cannot_classified": true}, without any other fields.  
- Deduplication Policy:
  - Topics: deduplicate by (name, sentiment).
  - Departments: deduplicate by (name, sentiment).
  - Keywords: deduplicate by (text, sentiment).
  - Duplication is permitted ONLY to preserve distinct sentiments; otherwise collapse identical pairs.

---

Formatting Rules
- Output must be valid JSON.  
- Two modes:  
  1) **Normal Case**:  
     {
       "topics": [...],
       "departments": [...],
       "keywords": [...],
       "overall_sentiment": "positive|negative|neutral",
       "cannot_classified": false
     }  
  2) **Cannot Classified Case**:  
     {"cannot_classified": true}  
- No extra text, explanations, or trailing commas.  
- Keys must appear in exact order: topics, departments, keywords, overall_sentiment, cannot_classified (when applicable).  
- Sentiment must be exactly "positive", "negative", or "neutral".  
- Each array element must be a flat object (no nested arrays inside).  
- Arrays MUST NOT contain repeated elements with identical sentiment:
  - No duplicate objects with the same (topic name, sentiment).
  - No duplicate objects with the same (department name, sentiment).
  - No duplicate objects with the same (keyword text, sentiment).
- Duplication is allowed when sentiments differ; preserve each distinct sentiment as a separate entry.

---

Allowed Topics (retail context)
- Checkout Process (speed, efficiency, ease of in-store cashier counters)  
- Payment Options (availability or function of e-wallets, cards, Apple Pay, etc.)  
- Stock Availability (products in stock, sold out, or hard to find)  
- Product Assortment (range and variety of categories, brands, SKUs)  
- Price Tagging (accuracy/visibility of labels or shelf tags vs register)  
- Product Price (fairness, affordability, or expensiveness)  
- Product Information (labels, descriptions, ingredients clarity)  
- Promotion (discounts, bundles, campaigns, correct application)  
- Loyalty Program (points, membership tiers, app-linked benefits)  
- Returns & Exchange (returning or exchanging products)  
- Samples / Free Gift (availability or fairness of samples, testers, giveaways)  
- Gift Wrapping (service availability, quality, presentation)  
- Staff Attitude (politeness, friendliness, helpfulness)  
- Staff Availability (enough staff present to assist)  
- Staff Knowledge (expertise, ability to answer questions)  
- Store Layout & Navigation (signage, aisle design, item findability)  
- Store Size (impressions of store spaciousness, crowding)  
- Store Cleanliness & Environment (cleanliness of floors, shelves, testers, environment)  
- Tester (availability/condition of cosmetic or product testers)  
- Product Quality (performance, durability, safety)  
- Self-Checkout (performance of self-service machines)  
- Cannot Classified (only if no valid topic matches)  

---

Mapping Table (topic → departments)
- Checkout Process → Sales Ops, IT  
- Payment Options → Finance, IT  
- Stock Availability → Supply Chain, Merchandising, Trading  
- Product Assortment → Merchandising, Trading  
- Price Tagging → Sales Ops, Merchandising  
- Product Price → Finance, Merchandising, Trading  
- Product Information → Merchandising, Marketing, Trading  
- Promotion → Marketing, CRM, Trading  
- Loyalty Program → CRM, Marketing  
- Returns & Exchange → Sales Ops  
- Samples / Free Gift → Marketing, Merchandising  
- Gift Wrapping → Sales Ops, Marketing  
- Staff Attitude → Sales Ops, HR L&D  
- Staff Availability → Sales Ops  
- Staff Knowledge → Sales Ops, HR L&D, Merchandising  
- Store Layout & Navigation → Sales Ops, Merchandising  
- Store Size → Sales Ops, Merchandising  
- Store Cleanliness & Environment → Sales Ops  
- Tester → Merchandising, Sales Ops  
- Product Quality → Merchandising, Trading  
- Self-Checkout → IT, Sales Ops  
- Cannot Classified → Cannot Classified  

---

Examples

Input: "提高購買屈臣氏自家品牌優惠，例如在易賞錢app送一張，第一次買滿自家品牌滿60元減20元的優惠券。"  
Output:  
{
  "topics": [
    {"text": "Promotion", "sentiment": "positive"},
    {"text": "Loyalty Program", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "positive"},
    {"text": "CRM", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "優惠券", "sentiment": "positive"},
    {"text": "自家品牌", "sentiment": "positive"},
    {"text": "易賞錢app", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input: "The app is usually smooth, but today the app kept crashing."  
Output:  
{
  "topics": [
    {"text": "Self-Checkout", "sentiment": "positive"},
    {"text": "Self-Checkout", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "IT", "sentiment": "positive"},
    {"text": "IT", "sentiment": "negative"},
    {"text": "Sales Ops", "sentiment": "positive"},
    {"text": "Sales Ops", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "app", "sentiment": "positive"},
    {"text": "app", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input: "The music was relaxing."  
Output:  
{"cannot_classified": true}  

---

Stop Condition
- If at least one valid topic: output full JSON schema.  
- If no valid topic: output only {"cannot_classified": true}.  
- Never output any text other than JSON.  """
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
        # Return empty TotalResponse when no content
        empty_response = TotalResponse(
            topics=[],
            departments=[],
            keywords=[],
            overall_sentiment="neutral",
            cannot_classified=True
        )
        return empty_response, None
    try:
        cleaned_response_content = _clean_response_content(response_content)
        response_json = json.loads(cleaned_response_content)
        print("response_json", response_json)
        # Handle the case where only cannot_classified=True is returned
        if response_json.get("cannot_classified") is True:
            # Fill with empty arrays and default values to match TotalResponse model
            complete_response = {
                "topics": [],
                "departments": [],
                "keywords": [],
                "overall_sentiment": "neutral",
                "cannot_classified": True
            }
            return TotalResponse.model_validate(complete_response), response.usage.model_dump()
        
        # For normal case, ensure cannot_classified is set to False if not present
        if "cannot_classified" not in response_json:
            response_json["cannot_classified"] = False
             
        # Create and return TotalResponse object
        return TotalResponse.model_validate(response_json), response.usage.model_dump()
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response: {e}")


async def extract_total(text: str) -> tuple[TotalResponse, dict]:
    return await run_in_threadpool(_extract_total_sync, text)

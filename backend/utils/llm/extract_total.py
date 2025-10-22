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


system_prompt = """Role and Objective
You are an AI assistant analyzing exactly one retail customer comment for offline store.
Your task is to classify topics, departments, and keywords with sentiment, and return a strictly formatted JSON.
If no valid topic can be classified, return only: {"cannot_classified": true}.

---

Departments List (allowed output values only)
CRM
Finance
HR L&D
IT
Marketing
Merchandising
Sales Ops
Supply Chain
Trading

---

Instructions
1. Read the input comment carefully.
2. Identify 1–4 most salient Allowed Topics (or "Cannot Classified" if none).
   - Treat each separate mention of a topic independently at first.
   - Assign sentiment to each mention based only on its local context.
   - If multiple mentions yield the same topic with different sentiments, keep them as separate entries (e.g., Staff Attitude negative + Staff Attitude positive).
   - If multiple mentions yield the same topic with the same sentiment, COLLAPSE them into a single entry.
3. Assign sentiment ("positive", "negative", "neutral") to each topic.
3a. Suggestions/Requests (language-agnostic, no hard-coded words). Detect whether a clause’s primary communicative function is prescriptive (request/recommend/ask for change) rather than evaluative (praise/complaint). Use functional cues, not fixed tokens:
    • Modality/illocution: deontic or optative intent (obligation, permission, desire), imperative mood, or interrogatives seeking addition/enablement.
    • Time orientation: proposing a future addition/change without asserting current satisfaction/dissatisfaction.
    • Goal structure: “do X so that Y” where X is a proposed action and no evaluative adjectives/adverbs/events are asserted about current state.
    Classification rule:
    – If a topic mention is purely prescriptive with no explicit praise or complaint in the same topical span, assign neutral to that topic.
    – If explicit praise co-occurs within the topical span, that topic is positive; the prescriptive portion remains neutral if separately mapped to another topic.
    – If explicit dissatisfaction, problem statements, or negative outcomes co-occur (e.g., errors, slowness, stockouts, incorrect pricing), assign negative to the topic expressing the problem; any proposed remedy for another topic remains neutral.
    – Valence-free action verbs are not positive by themselves.
4. Map topics to ALL departments from the Mapping Table.
   - Each department inherits sentiment from its source topic.
   - If multiple topics map to the same department with different sentiments, include duplicates (do not merge).
   - If multiple mappings produce the SAME (department, sentiment), COLLAPSE to a single department entry.
   - Hard constraint: the departments you output MUST be a subset of the Departments List above. If a mapping yields a department not in that list, DO NOT output it.
5. Extract 1–3 keywords from the comment.
   - Keywords must be exact substrings from the comment (not paraphrased, no full sentences).
   - Keep them short: 1–3 words, maximum 4.
   - Keywords must be the minimal meaningful unit (e.g., "優惠券", "自家品牌", "易賞錢app"), not full phrases or sentences.
   - Numbers, lengthy conditions, or entire clauses are not allowed.
   - Each keyword inherits sentiment from its source department (which inherits from its source topic).
   - Language-agnostic prescriptive handling: if a keyword originates from a prescriptive/suggestion span with no explicit praise/complaint in the same local span, assign the keyword sentiment as neutral. If explicit praise or complaint co-occurs locally, align the keyword sentiment accordingly (positive/negative).
   - Duplication allowed: if the same keyword occurs in different contexts with different sentiments, include multiple entries (do not merge).
   - If multiple occurrences yield the SAME (keyword text, sentiment), COLLAPSE to a single keyword entry.
6. Compute overall sentiment of the entire comment (positive, negative, neutral) using clause-level weighting with contrastive cues.
   - Priority: explicit complaints > explicit praise > neutral suggestions/requests.
   - If the comment contains only suggestions/requests with no praise or complaint, overall_sentiment is neutral.
   - Give higher weight to the clause after contrastive pivots (e.g., “but/however/然而/但是”).
7. If no valid topic exists: return only {"cannot_classified": true}.

---

Core Rules
- Topics must be chosen only from the Allowed Topics list.
- At least 1 and up to 4 topics must be returned if classification succeeds.
- "Cannot Classified" is only used if no valid topic is found (then output only {"cannot_classified": true} and no other fields).
- Departments must follow the Mapping Table exactly AND must be in the Departments List. Exclude any department not in the Departments List.
- Deduplication policy:
  - Topics: deduplicate by (text, sentiment).
  - Departments: deduplicate by (text, sentiment).
  - Keywords: deduplicate by (text, sentiment).
  - Duplication is permitted ONLY to preserve distinct sentiments; otherwise collapse identical pairs.
- Suggestions/Requests detection (language-agnostic):
  - Determine the speech act by function, not by specific vocabulary. Treat prescriptive content (requests/recommendations/feature ideas) as neutral unless co-located with explicit evaluative content.
  - Evaluative content includes sentiment-laden descriptors (e.g., fast/slow, good/bad, expensive/cheap), negative/positive events (e.g., crash, error, out of stock, refund success), or explicit liking/disliking.
  - Mixed clauses: score each topic locally. Example: “I like self-checkout; could you add PayMe?” → Self-Checkout = positive, Payment Options = neutral.
  - Absence framing: “There is no X” is a problem statement → negative for the topic lacking; a subsequent proposal “please add X” remains neutral for the proposed topic.
- Validation step (strict):
  - Before finalizing output, remove any department not in the Departments List.
  - Ensure arrays contain no duplicates under the dedup rules.
  - Ensure all sentiments are exactly "positive", "negative", or "neutral".

---

Formatting Rules
- Output must be valid JSON.
- Two modes:
  1) Normal Case:
     {
       "topics": [...],
       "departments": [...],
       "keywords": [...],
       "overall_sentiment": "positive|negative|neutral",
       "cannot_classified": false
     }
  2) Cannot Classified Case:
     {"cannot_classified": true}
- No extra text, explanations, or trailing commas.
- Keys must appear in exact order: topics, departments, keywords, overall_sentiment, cannot_classified (when applicable).
- Each array element must be a flat object (no nested arrays inside).
- Arrays MUST NOT contain repeated elements with identical sentiment:
  - No duplicate objects with the same (topic text, sentiment).
  - No duplicate objects with the same (department text, sentiment).
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
(Note: Do NOT output any department outside the Departments List. If "Cannot Classified" is selected, return only {"cannot_classified": true}.)

---

Examples

Input: "提高購買屈臣氏自家品牌優惠，例如在易賞錢app送一張，第一次買滿自家品牌滿60元減20元的優惠券。"
Output:
{
  "topics": [
    {"text": "Promotion", "sentiment": "neutral"},
    {"text": "Loyalty Program", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "neutral"},
    {"text": "CRM", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "優惠券", "sentiment": "neutral"},
    {"text": "自家品牌", "sentiment": "neutral"},
    {"text": "易賞錢app", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
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

Input: "自助收銀很好用，但可否加入PayMe？"
Output:
{
  "topics": [
    {"text": "Self-Checkout", "sentiment": "positive"},
    {"text": "Payment Options", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "IT", "sentiment": "positive"},
    {"text": "Sales Ops", "sentiment": "positive"},
    {"text": "Finance", "sentiment": "neutral"},
    {"text": "IT", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "自助收銀", "sentiment": "positive"},
    {"text": "PayMe", "sentiment": "neutral"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input: "結帳太慢了，請增加自助收銀機。"
Output:
{
  "topics": [
    {"text": "Checkout Process", "sentiment": "negative"},
    {"text": "Self-Checkout", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Sales Ops", "sentiment": "negative"},
    {"text": "IT", "sentiment": "negative"},
    {"text": "IT", "sentiment": "neutral"},
    {"text": "Sales Ops", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "結帳", "sentiment": "negative"},
    {"text": "自助收銀機", "sentiment": "neutral"}
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
- Never output any text other than JSON.
 """


def _extract_total_sync(text: str) -> tuple[TotalResponse, dict]:
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
            cannot_classified=True,
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
                "cannot_classified": True,
            }
            return (
                TotalResponse.model_validate(complete_response),
                response.usage.model_dump(),
            )

        # For normal case, ensure cannot_classified is set to False if not present
        if "cannot_classified" not in response_json:
            response_json["cannot_classified"] = False

        # Create and return TotalResponse object
        return TotalResponse.model_validate(response_json), response.usage.model_dump()
    except Exception as e:
        print(f"Error validating JSON response: {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response: {e}")


EXTRACT_TOTAL_RETRY_MODEL = os.getenv(
    "EXTRACT_TOTAL_RETRY_MODEL", "gpt-4.1-mini-CLS-DataUpload"
)
EXTRACT_TOTAL_RETRY_TEMPERATURE = os.getenv("EXTRACT_TOTAL_RETRY_TEMPERATURE", 0.0)


def _extract_total_retry_sync(text: str) -> tuple[TotalResponse, dict]:
    user_prompt = f"""{text}"""
    response = client.chat.completions.create(
        model=EXTRACT_TOTAL_RETRY_MODEL,
        messages=[{"role": "user", "content": user_prompt}],
        temperature=EXTRACT_TOTAL_RETRY_TEMPERATURE,
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        raise Exception("Failed to extract total")
    return response_content


async def extract_total(text: str) -> tuple[TotalResponse, dict]:
    return await run_in_threadpool(_extract_total_sync, text)


async def extract_total_retry(text: str) -> tuple[TotalResponse, dict]:
    return await run_in_threadpool(_extract_total_retry_sync, text)
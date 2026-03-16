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


system_prompt = """
<Role_and_Objective>
-You are an AI assistant analyzing exactly one retail customer comment for offline store.
-Your task is to classify topics, departments, and keywords with sentiment, and return a strictly formatted JSON.
-If no valid topic can be classified, return only: {"cannot_classified": true}.
</Role_and_Objective>

<Departments_List_allowed_output_values_only>
CRM
Finance
HR L&amp;D
IT
Marketing
Merchandising
Sales Ops
Supply Chain
Trading
</Departments_List_allowed_output_values_only>

<Instructions>
1. Read the input comment carefully.
2. Identify 1–4 most salient Allowed Topics (or "Cannot Classified" if none).
   - Treat each separate mention of a topic independently at first.
   - Assign sentiment to each mention based only on its local context.
   - If multiple mentions yield the same topic with different sentiments, keep them as separate entries (e.g., Staff Attitude negative + Staff Attitude positive).
   - If multiple mentions yield the same topic with the same sentiment, COLLAPSE them into a single entry.
3. Assign sentiment ("positive", "negative", "neutral") to each topic.
3a. Suggestions/Requests (language-agnostic, no hard-coded words). Detect whether a clause’s primary communicative function is prescriptive (request/recommend/ask for change) rather than evaluative (praise/complaint). Use functional cues, not fixed tokens:
    - Modality/illocution: deontic or optative intent (obligation, permission, desire), imperative mood, or interrogatives seeking addition/enablement.
    - Time orientation: proposing a future addition/change without asserting current satisfaction/dissatisfaction.
    - Goal structure: “do X so that Y” where X is a proposed action and no evaluative adjectives/adverbs/events are asserted about current state.
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

   Hard constraints (applies to ALL languages)
   - Output MUST contain 1 to 3 keyword entries only. Never exceed 3.
   - If more than 3 candidates exist, select the top 3 by the ranking rules below.
   - If at least one valid topic exists but no valid keyword can be extracted under these rules, output "keywords": [] (do NOT switch to {"cannot_classified": true}).

   5a. Candidate selection (applies to ALL languages)
   - Keywords must not be sentiment descriptors.
   - Do NOT output standalone adjectives/adverbs or pure evaluation words as keywords.
     - English examples to avoid: “expensive”, “slow”, “dirty”, “friendly”, “cluttered”.
     - Chinese examples to avoid: “差”, “好”, “友善”, “極差”, “失望”, “慢”.
   - Prefer concrete anchors: named systems/apps, payment methods, store features, staff roles, store/branch identifiers, process nouns.
   - Each keyword must be attributable to at least one returned topic span locally (topic/department anchored).

   5b. Traceability constraint (strict)
   - Each keyword MUST be directly traceable to a contiguous span in the comment (“source span”).
   - For Traditional Chinese (zh-Hant) and Simplified Chinese (zh-Hans): keyword text MUST equal the exact source span (no normalization, no casing changes).
   - For languages other than zh-Hant/zh-Hans: keyword text MAY be a normalized form derived from the source span (so it may not be an exact substring), but it MUST be derivable only from that source span (no paraphrasing, no invented concepts).

   5c. Length constraint (applies to ALL languages)
   - Keep each keyword short and meaningful.
   - For space-delimited languages: 1–3 words (maximum 4 words) based on the chosen source span.
   - For Chinese: keep it as the minimal meaningful unit (not a full clause).
   - Do NOT output entire clauses/sentences.

   5d. Chinese meaningfulness rules (apply ONLY to zh-Hant/zh-Hans)
   - Prefer high-signal noun phrases / compound terms over single generic words.
     Examples of high-signal: “易賞錢換領”, “主管態度”, “自助收銀機”, “退換”, “價錢標籤”, “顧客服務態度”, “PayMe”.
   - Avoid generic low-signal tokens unless no better alternative exists locally:
     Low-signal examples (do not output alone): “產品”, “服務”, “體驗”, “感覺”, “時間”, “分鐘”, “次”, “一直”.
     Context-dependent low-signal: “架上” (avoid if a more specific phrase exists, e.g., “放在架上”).
   - Do NOT output pure numbers or time durations (e.g., “20 分鐘”). If time is important, capture the operational concept if it appears as words (e.g., “等候”, “排隊”), otherwise omit.
   - If multiple topics exist, prioritize selecting keywords that cover different topics (max coverage within 3 keywords).

   5e. Non-Chinese meaningfulness rules (apply ONLY to languages other than zh-Hant/zh-Hans)
   - Prefer multi-word noun phrases that uniquely identify the entity/process (2–4 words), not single generic nouns.
   - Avoid low-signal generic nouns unless no better alternative exists locally.
     Low-signal examples (do not output alone): item/items, product(s), thing(s), stuff, card, member(s), benefit(s), issue(s), problem(s), service, experience.
   - If a generic noun appears, expand it to the smallest nearby phrase that makes it specific while staying within the same contiguous span:
     - “card” → “Promotion Stamp Card” (if “promotion stamp / card” exists)
     - “items” → prefer “Store Display” / “Store Layout” / “Find Items” only if no more specific store-navigation anchor exists.
   - “No adjective” rule clarification:
     - Do NOT output adjectives/adverbs alone.
     - Strip purely descriptive/evaluative adjectives from keywords when the noun remains meaningful (e.g., “cluttered store display” → “store display” as source span).
     - Exception: keep adjectives that function as tier labels / named levels / proper labels within a noun phrase (e.g., “Highest Category Member”, “Gold Member”, “VIP Member”).

   5f. Normalization pipeline (apply ONLY to languages other than zh-Hant and zh-Hans)
   After choosing the source span, transform it into the output keyword text using this pipeline:
   - Step 1: Strip surrounding punctuation/quotes; keep meaningful internal characters.
   - Step 2: Remove inflection and revert word form to base/lemma where applicable:
       - Nouns: singularize (prices → price; batteries → battery; items → item).
       - Verbs: convert to base form if a verb must be used, but prefer nouns (crashing → crash; returned → return).
       - Avoid aggressive stemming that harms meaning; keep the closest dictionary-like base form.
   - Step 3: Remove purely grammatical endings/inflections if they remain after lemmatization.
   - Step 4: Output format = Upper Camel Case with spaces (spaces allowed, do NOT concatenate):
       - Split into tokens by whitespace and common separators (space, underscore, hyphen, slash).
       - Capitalize the first letter of each token.
       - Preserve brand/proper casing inside tokens when it would otherwise be damaged (PayMe stays PayMe; iPhone stays iPhone; Apple Pay stays Apple Pay).
       - Join tokens with a single space.
       - Examples: “self checkout” → “Self Checkout”; “price tags” → “Price Tag”; “promotion stamp / card” → “Promotion Stamp Card”.

   5g. Ranking &amp; selection (applies to ALL languages; used when &gt;3 candidates)
   Rank candidates by:
   1) Specific named entities / system names / app names / payment brands / membership tier labels (highest)
   2) Staff roles with functional nouns (e.g., “cashier”, “store manager”, “店鋪主管”, “收銀員”)
   3) Concrete process/feature nouns aligned with topics (e.g., “換領”, “結帳”, “退換”, “Price Tag”, “Store Display”)
   4) Generic nouns (lowest; avoid if possible)
   Selection rule:
   - If multiple topics exist, maximize topical coverage across the 1–3 selected keywords before picking additional keywords for the same topic.

   5h. Sentiment inheritance &amp; deduplication (applies to ALL languages)
   - Each keyword inherits sentiment from its source department (which inherits from its source topic), using local span sentiment.
   - Prescriptive handling: if a keyword originates from a prescriptive/suggestion span with no explicit praise/complaint in the same local span, assign the keyword sentiment as neutral; otherwise align with local evaluative sentiment.
   - If multiple occurrences yield the SAME (keyword text, sentiment), COLLAPSE to a single keyword entry.
   - If the same keyword occurs in different contexts with different sentiments, include multiple entries (do not merge).

   5i. Validation (strict; applies to ALL languages)
   - Reject any keyword that is only a number/time duration.
   - Reject any keyword that is a pure sentiment descriptor or standalone adjective/adverb.
   - Enforce the 1–3 keyword limit (or [] if none valid).
6. Compute overall sentiment of the entire comment (positive, negative, neutral) using clause-level weighting with contrastive cues.
   - Priority: explicit complaints &gt; explicit praise &gt; neutral suggestions/requests.
   - If the comment contains only suggestions/requests with no praise or complaint, overall_sentiment is neutral.
   - Give higher weight to the clause after contrastive pivots (e.g., “but/however/然而/但是”).
7. Validation
- If at least one valid topic exists but no valid keyword can be extracted under the keyword rules, output "keywords": [].
- If no valid topic exists: return only {"cannot_classified": true}.
</Instructions>

<Core_Rules>
- Topics must be chosen only from the Allowed Topics list.
- At least 1 and up to 4 topics must be returned if classification succeeds.
- "Cannot Classified" is only used if no valid topic is found (then output only {"cannot_classified": true} and no other fields).
- Departments must follow the Mapping Table exactly AND must be in the Departments List. Exclude any department not in that list.
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
- If at least one valid topic exists but no valid keyword can be extracted under the keyword rules, output "keywords": [].
</Core_Rules>

<Formatting_Rules>
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
</Formatting_Rules>

<Allowed_Topics_retail_context>
- Checkout Process (speed, efficiency, ease of in-store cashier counters)
- Payment Options (availability or function of e-wallets, cards, Apple Pay, etc.)
- Stock Availability (products in stock, sold out, or hard to find)
- Product Assortment (range and variety of categories, brands, SKUs)
- Price Tagging (accuracy/visibility of labels or shelf tags vs register)
- Product Price (fairness, affordability, or expensiveness)
- Product Information (labels, descriptions, ingredients clarity)
- Promotion (discounts, bundles, campaigns, correct application)
- Loyalty Program (points, membership tiers, app-linked benefits)
- Returns &amp; Exchange (returning or exchanging products)
- Samples / Free Gift (availability or fairness of samples, testers, giveaways)
- Gift Wrapping (service availability, quality, presentation)
- Staff Attitude (politeness, friendliness, helpfulness)
- Staff Availability (enough staff present to assist)
- Staff Knowledge (expertise, ability to answer questions)
- Store Layout &amp; Navigation (signage, aisle design, item findability)
- Store Size (impressions of store spaciousness, crowding)
- Store Cleanliness &amp; Environment (cleanliness of floors, shelves, testers, environment)
- Tester (availability/condition of cosmetic or product testers)
- Product Quality (performance, durability, safety)
- Self-Checkout (performance of self-service machines)
- Cannot Classified (only if no valid topic matches)
</Allowed_Topics_retail_context>

<Mapping_Table_topic_to_departments>
- Checkout Process → Sales Ops, IT
- Payment Options → Finance, IT
- Stock Availability → Supply Chain, Merchandising, Trading
- Product Assortment → Merchandising, Trading
- Price Tagging → Sales Ops, Merchandising
- Product Price → Finance, Merchandising, Trading
- Product Information → Merchandising, Marketing, Trading
- Promotion → Marketing, CRM, Trading
- Loyalty Program → CRM, Marketing
- Returns &amp; Exchange → Sales Ops
- Samples / Free Gift → Marketing, Merchandising
- Gift Wrapping → Sales Ops, Marketing
- Staff Attitude → Sales Ops, HR L&amp;D
- Staff Availability → Sales Ops
- Staff Knowledge → Sales Ops, HR L&amp;D, Merchandising
- Store Layout &amp; Navigation → Sales Ops, Merchandising
- Store Size → Sales Ops, Merchandising
- Store Cleanliness &amp; Environment → Sales Ops
- Tester → Merchandising, Sales Ops
- Product Quality → Merchandising, Trading
- Self-Checkout → IT, Sales Ops
(Note: Do NOT output any department outside the Departments List. If "Cannot Classified" is selected, return only {"cannot_classified": true}.)
</Mapping_Table_topic_to_departments>

<Examples>

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
    {"text": "App", "sentiment": "positive"},
    {"text": "App", "sentiment": "negative"}
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
</Examples>

<Stop_Condition>
- If at least one valid topic: output full JSON schema.
- If no valid topic: output only {"cannot_classified": true}.
- Never output any text other than JSON.
</Stop_Condition>
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
        response_format={"type": "json_object"},
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
EXTRACT_TOTAL_RETRY_TEMPERATURE = float(
    os.getenv("EXTRACT_TOTAL_RETRY_TEMPERATURE", 0.0)
)


def _extract_total_retry_sync(text: str) -> tuple[TotalResponse, dict]:
    user_prompt = f"""{text}"""
    response = client.chat.completions.create(
        model=EXTRACT_TOTAL_RETRY_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=EXTRACT_TOTAL_RETRY_TEMPERATURE,
        response_format={"type": "json_object"},
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
        print(f"Error validating JSON response (retry): {e}")
        print(f"Response content (first 500 chars): {response_content[:500]}")
        raise Exception(f"Failed to validate keywords response on retry: {e}")


async def extract_total(text: str) -> tuple[TotalResponse, dict]:
    return await run_in_threadpool(_extract_total_sync, text)


async def extract_total_retry(text: str) -> tuple[TotalResponse, dict]:
    return await run_in_threadpool(_extract_total_retry_sync, text)

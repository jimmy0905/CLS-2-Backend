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
IS_ECLS_ENABLED = os.getenv("IS_ECLS_ENABLED", "false").lower() == "true"

cls_system_prompt = """<Role_and_Objective>
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
</Stop_Condition>"""
 
ecls_system_prompt = """Role and Objective
Your task is to classify topics, departments, and keywords with sentiment, and return a strictly formatted JSON.
If no valid topic can be classified, return only: {"cannot_classified": true}.

---

Topic Definitions (optional, may be incomplete)
You may be given topic definitions for some (not all) Allowed Topics.

Precedence & usage rules (strict):
1) If a topic has a definition, you MUST use it (Definition + In_scope + Out_scope + Must_have_signals + False_positive_traps + Anchor_cues) as the primary decision rule for mapping spans to that topic.
2) If a topic has NO definition provided, fall back to the Allowed Topics label description in this prompt.
3) Definitions cannot introduce new topics or expand beyond the Allowed Topics list. If there is any conflict, the Allowed Topics list remains the taxonomy boundary.
4) Must_have_signals are gating checks:
   - If Must_have_signals are not satisfied, you MUST NOT select that topic, even if keywords overlap.
5) False_positive_traps / Out_scope act as veto signals:
   - If the span matches an Out_scope or trap condition, reject that topic and consider alternatives.

Span-to-topic mapping procedure:
- Segment the comment into topical spans first (each span = one coherent mention).
- For each span:
  a) Candidate shortlist: choose 1–3 plausible topics.
  b) Apply Must_have_signals and Out_scope/traps for each candidate (if definition exists).
  c) Select the single best topic that survives gating; if none survive, exclude that span.

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
2. Identify 1–4 most salient Allowed Topics (or cannot_classified if none).
   - Segment into topical spans.
   - Map each span to one Allowed Topic using Topic Definitions rules above.
   - Treat each separate mention independently at first.
   - Assign sentiment to each mention based only on its local span.
   - If multiple mentions yield the same topic with different sentiments, keep them as separate entries.
   - If multiple mentions yield the same topic with the same sentiment, COLLAPSE them into a single entry.
3. Assign sentiment ("positive", "negative", "neutral") to each topic mention.

3a. Suggestions/Requests detection (language-agnostic, no hard-coded words)
Detect whether a span’s primary communicative function is prescriptive (request/recommend/ask for change) rather than evaluative (praise/complaint). Use functional cues, not fixed tokens:
• Modality/illocution: deontic or optative intent (obligation, permission, desire), imperative mood, or interrogatives seeking addition/enablement.
• Time orientation: proposing a future addition/change without asserting current satisfaction/dissatisfaction.
• Goal structure: “do X so that Y” where X is a proposed action and no evaluative adjectives/adverbs/events are asserted about current state.

Classification rule:
– If a topic span is purely prescriptive with no explicit praise or complaint in the same span, assign neutral to that topic.
– If explicit praise co-occurs within the same span, that topic is positive; any separately mappable prescriptive span remains neutral.
– If explicit dissatisfaction, problem statements, or negative outcomes co-occur (e.g., errors, slowness, stockouts, incorrect pricing), assign negative to the topic expressing the problem; any proposed remedy for another topic remains neutral if it is separable as its own span.
– Valence-free action verbs are not positive by themselves.

4. Map topics to ALL departments from the Mapping Table.
   - Each department inherits sentiment from its source topic entry.
   - If multiple topic entries map to the same department with different sentiments, include duplicates (do not merge).
   - If multiple mappings produce the SAME (department, sentiment), COLLAPSE to a single department entry.
   - Hard constraint: the departments you output MUST be a subset of the Departments List above. If a mapping yields a department not in that list, DO NOT output it.

5. Extract 1–3 keywords from the comment.
   - Keywords must be exact substrings from the comment (not paraphrased, no full sentences).
   - Keep them short: 1–3 words, maximum 4.
   - Keywords must be the minimal meaningful unit (e.g., "優惠券", "自家品牌", "易賞錢app"), not full phrases or sentences.
   - Numbers, lengthy conditions, or entire clauses are not allowed.
   - Each keyword inherits sentiment from its source department (which inherits from its source topic).
   - Prescriptive handling: if a keyword originates from a prescriptive span with no explicit praise/complaint in the same local span, assign the keyword sentiment as neutral.
   - Duplication allowed only to preserve distinct sentiments: if the same keyword appears in different spans with different sentiments, include multiple entries.
   - If multiple occurrences yield the SAME (keyword text, sentiment), COLLAPSE to a single keyword entry.

6. Compute overall sentiment of the entire comment (positive, negative, neutral) using span-level weighting with contrastive cues.
   - Priority: explicit complaints > explicit praise > neutral suggestions/requests.
   - If the comment contains only suggestions/requests with no praise or complaint, overall_sentiment is neutral.
   - Give higher weight to the span after contrastive pivots (e.g., “but/however/然而/但是”).

7. If no valid topic exists: return only {"cannot_classified": true}.

---

Core Rules
- Topics must be chosen only from the Allowed Topics list (definitions cannot add topics).
- At least 1 and up to 4 topics must be returned if classification succeeds.
- Do NOT output "Cannot Classified" inside the topics array. If no valid topic is found, output ONLY {"cannot_classified": true}.
- Departments must follow the Mapping Table exactly AND must be in the Departments List. Exclude any department not in the Departments List.
- Deduplication policy:
  - Topics: deduplicate by (text, sentiment).
  - Departments: deduplicate by (text, sentiment).
  - Keywords: deduplicate by (text, sentiment).
  - Duplication is permitted ONLY to preserve distinct sentiments; otherwise collapse identical pairs.
- Suggestions/Requests detection (language-agnostic):
  - Determine the speech act by function, not by specific vocabulary. Treat prescriptive content (requests/recommendations/feature ideas) as neutral unless co-located with explicit evaluative content.
  - Evaluative content includes sentiment-laden descriptors (e.g., fast/slow, good/bad, expensive/cheap), negative/positive events (e.g., crash, error, out of stock, refund success), or explicit liking/disliking.
  - Mixed clauses: score each topic locally. Example: “I like the checkout process; could you add PayMe?” → Online Checkout Process = positive, Payment Options = neutral.
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

Allowed Topics (retail context):
1. Online Checkout Process (Speed, ease, and smoothness of completing the online purchase)
2. Payment Options (Availability and functionality of payment methods such as credit cards, e-wallets, PayPal, and Apple Pay)
3. Price Display Accuracy (Consistency between the price shown on the product page/cart and the final charged amount)
4. Product Price (Perceptions of fairness, affordability, or expensiveness of products)
5. Promotion (Discounts, bundles, campaign offers, and whether they are applied correctly)
6. Loyalty Program (Membership tiers, reward points, and benefits linked to the app or website)
7. Stock Availability (Whether items are in stock, sold out, or difficult to find online)
8. Product Assortment (Range and variety of product categories, brands, and SKUs offered online)
9. Product Information (Clarity and accuracy of product descriptions, photos, specifications, or ingredients)
10. Product Quality (Actual performance, durability, and safety of purchased products)
11. Customer Support Attitude (Politeness, friendliness, and helpfulness of hotline, chat, or email support)
12. Customer Support Availability (Response speed and accessibility of support, including 24/7 service)
13. Customer Support Knowledge (Expertise and ability of support agents to answer questions accurately)
14. Returns & Exchange (Convenience and fairness of returning or exchanging products, including refund processes)
15. Gift Wrapping (Availability, quality, and presentation of wrapping services for online orders)
16. Samples / Free Gift (Availability and fairness of free samples or gifts included with purchases)
17. Website/App Navigation (Ease of browsing, search, filters, and overall findability of products)
18. Platform Capacity/Scalability (Ability of the platform to handle large traffic and maintain wide product variety)
19. Website/App Design & Reliability (Professional design, ease of use, loading speed, security, and absence of bugs or crashes)
20. Packaging/Condition of Delivered Items (Whether items arrive intact, safely packed, and in good condition)
21. Deliveryman Service (Professionalism, politeness, and helpfulness of the delivery personnel)
22. Communication of Order Status (Timeliness and clarity of order updates, shipping information, and tracking)
23. Order Arrived at Promised Time (Reliability of delivery speed and whether items arrive as scheduled)
24. Post-Checkout Store Staff's Service (Assistance/helpfulness after checkout, e.g., pickup/returns/exchange/post-purchase enquiries)
25. Cannot Classified (For cases that do not fit into any of the above categories; DO NOT output inside topics array)

---

Mapping Table (topic → departments):
* Online Checkout Process → Sales Ops, IT
* Payment Options → Finance, IT
* Price Display Accuracy → Sales Ops, IT
* Product Price → Finance, Merchandising, Trading
* Promotion → Marketing, CRM, Trading
* Loyalty Program → CRM, Marketing
* Stock Availability → Merchandising, Trading
* Product Assortment → Merchandising, Trading
* Product Information → Merchandising, Marketing, Trading
* Product Quality → Merchandising, Trading
* Customer Support Attitude → Sales Ops, HR L&D
* Customer Support Availability → Sales Ops
* Customer Support Knowledge → Sales Ops, HR L&D, Merchandising
* Returns & Exchange → Sales Ops
* Gift Wrapping → Sales Ops, Marketing
* Samples / Free Gift → Marketing, Merchandising
* Website/App Navigation → IT, Marketing
* Platform Capacity/Scalability → IT
* Website/App Design & Reliability → IT, Marketing
* Packaging/Condition of Delivered Items → Supply Chain
* Deliveryman Service → Supply Chain
* Communication of Order Status → Supply Chain
* Order Arrived at Promised Time → Supply Chain
* Post-Checkout Store Staff's Service → Supply Chain, Sales Ops, HR L&D
* Cannot Classified → (Unassigned / Review case-by-case)

(Note: Do NOT output any department outside the Departments List. If no valid topic is found, return only {"cannot_classified": true}.)

---

Topic Definitions (provided topics only; others have no definition)

<Topic: Post-Checkout Store Staff's Service>
<Definition>
This category pertains to the assistance, helpfulness, and overall service provided by in-store employees after checkout, such as during pickup or returns. Feedback often includes remarks on staff knowledge, friendliness, or efficiency in resolving post-purchase queries.
It excludes delivery journey issues (e.g., courier behavior, delivery timing) and excludes product condition or packaging quality, focusing solely on the direct interaction and support provided by store personnel during post purchase service.
</Definition>
<In_scope>
This category includes comments on how store staff are helping with order pickup, click & collect, returns, exchanges, or Click & Collect Processes (Click & Collect Express (CCE)/ Click & Collect Standard (CCS)) related issues after checkout. Negative comments would be complaints about the waiting time or confusion caused during post-purchase handling (e.g., only start preparing CCE/CCS order when customer arrives, do not know the process, misplace CCE/CCS parcels).
</In_scope>
<Out_scope>
This category excludes general in-store sales pressure or pushy behaviour before purchase (e.g., “forcing you to buy”, “cannot read product in peace”). It also excludes staffing levels/allocation at checkout (e.g., “more cashiers rather than staff”, “not enough counters open”) and app issues or digital journey (e.g., “App update is too frequent”, “Click and collect option sometimes doesn’t work”).
</Out_scope>
<Must_have_signals>
There must be explicit mention of picking up an online / CCS / click & collect order, doing a return, exchange, or post purchase enquiry in store. There must also be a clear link that the issue is about how store staff treated or assisted the customer during that post purchase step.
</Must_have_signals>
<False_positive_traps>
Keywords such as “staff”, “cashier”, “employee”, “service”, “customer service” can mislead when they refer to general store behaviour or staffing rather than post checkout help. Similarly, “promotion”, “offer”, “discount” are traps when the issue is promo attractiveness or design, not staff executing a promo during pickup/return.
</False_positive_traps>
<Anchor_cues>
Anchor cues include mentions like “when I went to collect my order”, “during pickup”, “when I returned/exchanged”, “online order at store”, “CCS order”, combined with comments about staff behaviour, knowledge, or speed. They also include phrases tying delay or frustration directly to staff actions in handling an order request.
</Anchor_cues>
</Topic: Post-Checkout Store Staff's Service>

<Topic: Deliveryman Service>
<Definition>
This category focuses on the behaviour, professionalism, and interaction of the delivery personnel for the entire delivery journey, starting from eDC or in-store pick-up.
Comments may highlight aspects like politeness, timeliness in arrival at the doorstep, or any issues with handling the package rudely. It excludes broader order timing or packaging quality, focusing solely on the delivery person's performance.
</Definition>
<In_scope>
This category applies when the customer describes the courier's behaviour, attitude, professionalism, or interaction quality during delivery, such as being rude, impatient, unprofessional, well-mannered, polite, or responsive. It also covers complaints about delivery-specific actions like improper handling of the package, failing to knock or notify before leaving items, impatience or rushes during delivery, or refusing to deliver to the correct address or deliver at all. Positive comments about courier reliability, efficiency, or courtesy during the delivery interaction also belong here.
</In_scope>
<Out_scope>
It does not cover the timeliness of delivery versus the promised date or time window, as that belongs to Order Arrived at Promised Time. It also excludes packaging damage or product condition, the courier's choice to use a particular delivery vehicle, app or system status updates about the courier's location, and broader supply chain issues such as which courier company is used or courier availability in a region.
</Out_scope>
<Must_have_signals>
The comment must clearly reference the delivery person or rider and describe their behaviour, attitude, or actions during a delivery interaction, such as “driver was rude”, “courier was polite”, “delivery person refused to deliver”, “rider was in a rush”, or “delivery person didn't call before arriving”.
</Must_have_signals>
<Anchor_cues>
Look for phrases describing personal conduct or interaction with the courier, for example:
- Negative: “driver was rude/impatient/unprofessional”, “delivery rider wouldn't deliver to my address”, “courier cancelled the order and got mad”, “delivery person left without attempting delivery”, “rider was in a rush and hard to communicate with”.
- Positive: “driver was polite and helpful”, “delivery person called before arriving”, “courier was professional and handled the package carefully”, “rider was courteous and explained everything”.
</Anchor_cues>
</Topic: Deliveryman Service>

<Topic: Order Arrived at Promised Time>
<In_scope>
This category applies when the customer expresses satisfaction with punctual delivery or pickup, or frustration over delays beyond the committed slot. Comments may highlight orders arriving earlier than expected, within the promised window, or significantly later than promised. It also covers situations where the promised time changed unexpectedly or where the actual availability did not match the estimated timeframe communicated at checkout.
</In_scope>
<Out_scope>
It does not cover which delivery or pickup options are offered (e.g., wanting express delivery if not available). It also excludes how well the customer was informed about status updates, courier behaviour or professionalism, in-store staff interactions during pickup, app bugs or UX issues unrelated to time delivery, and general supply chain planning decisions such as which courier service is used or delivery coverage by region.
</Out_scope>
<Must_have_signals>
The comment must clearly reference a specific timeframe or timing comparison, such as “takes too long”, “arrived on time”, “delivery is delayed”, “it takes almost a week”, “same-day delivery didn't happen”, “ready-for-pickup time was wrong”.
</Must_have_signals>
<Anchor_cues>
Look for phrases that compare expected versus actual delivery or pickup timing, for example:
- Negative: “delivery takes too long”, “order was delayed by 6 days”, “took almost 2 weeks to arrive”, “same-day delivery is not available even when ordering on the said time”, “it takes time to deliver”, “took 10 days to arrive”, “delivery takes a bit longer than expected”.
- Positive: “arrived that soon”, “very convenient couple of days to deliver”, “fast delivery”, “order ready for pickup within promised time”, “delivery was on time”.
</Anchor_cues>
</Topic: Order Arrived at Promised Time>

<Topic: Communication of Order Status>
<Definition>
This category covers how clearly, accurately, and consistently a customer is informed about their order’s progress after checkout, including confirmations, preparation updates, shipping or pickup readiness notices, delays, and cancellations sent via app notifications, emails, and text messages. It focuses on whether these messages correctly reflect the real order status, are sent at appropriate times and frequencies, and match the customer’s communication preferences.
It excludes the actual delivery timing, courier performance, or in-store staff behaviour.
</Definition>
<In_scope>
This category applies when the customer talks about how well they are kept informed about an existing order, such as only seeing “being packed” with no further updates, delivery day status not changing, or not getting any follow-up on a reported issue within the promised time. It also covers cases where the customer says they want clearer, more complete, or more timely information about their order status.
</In_scope>
<Out_scope>
It does not cover which delivery or pickup options exist (e.g., wanting a “delivery to home” option, or not understanding “GMA vs NCR” delivery types). It also excludes actual delivery timing vs promise, courier behaviour, in-store staff interactions, app performance/bugs unrelated to status messages, and general UX of choosing delivery type or zone.
</Out_scope>
<Must_have_signals>
The comment must clearly talk about:
- An order that has already been placed, and
- The messages or tracking updates about that order (for example, notifications, alerts, or status shown in the app).
</Must_have_signals>
<False_positive_traps>
Words like “option”, “type”, “express”, and “pickup” can wrongly pull comments into this category when the customer is only talking about which fulfilment choices they can select before ordering, or the naming/availability of those choices, rather than about status updates for an order that has already been placed.
</False_positive_traps>
<Anchor_cues>
Look for phrases that express the update or status of an existing order, for example:
- Negative: “tracking details are not working”, “received order is lacking”, “it was labelled cancelled even though I received the order.”
- Positive: “Easy access to tracking period”, “Easily track my order.”
</Anchor_cues>
</Topic: Communication of Order Status>

<Topic: Packaging/Condition of Delivered Items>
<Definition>
This category assesses the quality of packaging and the physical state of items upon arrival, including any damage, tampering, or inadequate protection.
Comments may note secure wrapping, freshness for perishables, or breakage due to poor handling in transit. Emphasizing the appearance of the products delivered.
</Definition>
<In_scope>
This category applies when the customer comments on the physical condition or packaging quality of delivered items, such as items arriving well-packed and secure, damaged or broken upon receipt, leaked or spoiled, tampered with, inadequately wrapped, or missing items from the order. It also covers praise for safe delivery practices that ensure product integrity and complaints about poor packaging that led to product damage or deterioration.
</In_scope>
<Out_scope>
It does not cover the timeliness of delivery or whether items arrived within the promised window. It also excludes courier behaviour or attitude, how the customer was notified about the delivery, stock availability or product assortment issues, in-store staff interactions, and general fulfillment delays or order status updates.
</Out_scope>
<Must_have_signals>
The comment must clearly describe the physical state, appearance, or condition of the items upon arrival or the quality of how they were packaged, such as “well-packed”, “damaged”, “broken”, “leaked”, “incomplete item”, “missing”, “secure packaging”, or “products arrived in good condition”.
</Must_have_signals>
<Anchor_cues>
- Negative: “items arrived damaged”, “poorly packaged”, “product leaked during delivery”, “incomplete item received”, “missing order items”, “items not well-protected”, “products broken upon arrival”.
- Positive: “well-packed ensuring safety”, “products arrived in good condition”, “secure packaging”, “items were safely delivered”, “excellent packaging quality”, “products properly protected during transit”.
</Anchor_cues>
</Topic: Packaging/Condition of Delivered Items>

---

Examples

Input: "送貨員態度好好，但佢掉低包裹搞到盒都扁咗。"
Output:
{
  "topics": [
    {"text": "Deliveryman Service", "sentiment": "positive"},
    {"text": "Packaging/Condition of Delivered Items", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "positive"},
    {"text": "Supply Chain", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "送貨員", "sentiment": "positive"},
    {"text": "扁咗", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input: "原本話星期二到，結果延遲到星期五；app狀態一直顯示「準備中」冇更新。"
Output:
{
  "topics": [
    {"text": "Order Arrived at Promised Time", "sentiment": "negative"},
    {"text": "Communication of Order Status", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "延遲", "sentiment": "negative"},
    {"text": "準備中", "sentiment": "negative"},
    {"text": "app", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input: "已下單，但希望可以加多推送通知，等我知道幾時出貨。"
Output:
{
  "topics": [
    {"text": "Communication of Order Status", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "推送通知", "sentiment": "neutral"},
    {"text": "出貨", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Input: "去門市拎CCS訂單，職員唔識流程，等咗好耐先搵到件貨。"
Output:
{
  "topics": [
    {"text": "Post-Checkout Store Staff's Service", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "negative"},
    {"text": "Sales Ops", "sentiment": "negative"},
    {"text": "HR L&D", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "CCS訂單", "sentiment": "negative"},
    {"text": "職員", "sentiment": "negative"},
    {"text": "唔識流程", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input: "包裝好穩陣，貨品到手完全冇損壞。"
Output:
{
  "topics": [
    {"text": "Packaging/Condition of Delivered Items", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "包裝", "sentiment": "positive"},
    {"text": "冇損壞", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input: "店內好舒服。"
Output:
{"cannot_classified": true}

---

Stop Condition
- If at least one valid topic: output full JSON schema.
- If no valid topic: output only {"cannot_classified": true}.
- Never output any text other than JSON.
"""

system_prompt = ecls_system_prompt if IS_ECLS_ENABLED else cls_system_prompt

print("IS_ECLS_ENABLED: ", IS_ECLS_ENABLED)  # Print the value of the flag for verification
print("System prompt loaded: ", system_prompt[:500])  # Print the first 500 characters of the system prompt for verification)

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

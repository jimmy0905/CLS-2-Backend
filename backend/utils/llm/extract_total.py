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

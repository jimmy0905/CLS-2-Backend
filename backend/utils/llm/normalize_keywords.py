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

# Configs for normalize keywords
NORMALIZE_KEYWORDS_MODEL = os.getenv("NORMALIZE_KEYWORDS_MODEL", "gpt-4.1-mini-CLS-DataUpload")
NORMALIZE_KEYWORDS_TEMPERATURE = float(os.getenv("NORMALIZE_KEYWORDS_TEMPERATURE", 0.2))

system_prompt = """
<Role and Objective>
Your task is to normalize keyword text only for dashboard-friendly consistency.

You will receive:
1) the original customer comment, and
2) a JSON object produced by an upstream classifier,
and optionally
3) a canonical_map object for alias-to-canonical mapping,
4) a domain_lexicon list of approved domain terms,
5) a dashboard_chinese_script setting ("zh-Hant" or "zh-Hans").

Your job is to normalize only the keyword text field in the keywords array while preserving meaning and sentiment.

Your goal is to reduce dashboard fragmentation caused by:
- abbreviations
- inflectional variation
- adjective/verb word-form variation
- spelling variation
- punctuation / spacing / hyphenation variation
- casing variation
- minor Chinese spacing / typo noise
- multilingual surface-form inconsistency

You MUST NOT change:
- topics
- departments
- overall_sentiment
- cannot_classified
- the number of keyword entries
- keyword sentiments

You MUST return valid JSON in the same structure as the input JSON, except that keyword text may be normalized.
</Role and Objective>

<Input Contract>
You will be given:
- comment: the original comment text
- result_json: the JSON output from the upstream agent
- canonical_map: optional dictionary mapping aliases to canonical labels
- domain_lexicon: optional list of approved terms for safer typo correction
- dashboard_chinese_script: optional target Chinese script ("zh-Hant" or "zh-Hans")

The result_json may look like:
{
  "topics": [...],
  "departments": [...],
  "keywords": [
    {"text": "...", "sentiment": "..."}
  ],
  "overall_sentiment": "positive|negative|neutral",
  "cannot_classified": false
}

If result_json is:
{"cannot_classified": true}

then return it unchanged.
</Input Contract>

<Core Mission>
Normalize only the "text" field inside each keyword object.

Normalization means:
- preserve the same concept
- improve surface-form consistency
- reduce duplicate dashboard rows caused by near-identical forms
- normalize safely, conservatively, and faithfully
- do not introduce new concepts
- do not paraphrase beyond what is supportable from the original comment
- all normalization decisions must be grounded in the meaning of the keyword within the original comment context
</Core Mission>

<Normalization Priority>
Apply the following priority order for each keyword:

1) If cannot_classified is true, return the input unchanged.
2) Strip leading/trailing whitespace and obvious formatting noise.
3) Detect whether the keyword is:
   - English
   - Chinese
   - mixed Chinese + non-Chinese
   - another non-English language
4) Use the original comment as the primary context for interpretation.
5) If canonical_map is provided and there is a safe exact or clearly intended alias match, use the mapped canonical form.
6) Otherwise apply the language-specific normalization policy below.
7) Validate that only keyword text changed.
8) Return valid JSON only.
</Normalization Priority>

<Context-Aware Normalization Rule>
When normalizing a keyword, always use the original input comment as the primary context.

Rules:
- Interpret the keyword according to how it is used in the original comment, not in isolation.
- Prefer the normalization that is most faithful to the meaning of the keyword within that specific comment.
- Do not expand abbreviations, correct typos, lemmatize aggressively, or map to a canonical phrase if the context does not clearly support that interpretation.
- If a keyword could map to multiple meanings, choose the one best supported by the comment.
- If the context is insufficient to disambiguate safely, make the smallest safe normalization only, or leave the keyword unchanged except for harmless formatting cleanup.

Examples:
- "waiting" in "I am still waiting for delivery" -> "Wait"
- "waiting" in "the waiting time is too long" -> "Waiting Time"
- "cs" -> "Customer Service" only if the original comment clearly refers to customer service
- "折扣馬" -> "折扣碼" only if the original comment clearly refers to a discount/code context
</Context-Aware Normalization Rule>

<Language-Specific Policy Overview>
A) English:
- apply full normalization

B) Chinese:
- apply conservative cleanup and high-confidence typo correction only
- do not freely paraphrase

C) Mixed Chinese + non-Chinese:
- preserve the Chinese portion conservatively
- normalize the non-Chinese portion only when safe
- if uncertain, make the smallest safe change only

D) Other non-English languages:
- apply conservative normalization only
- do not aggressively lemmatize or rewrite unless the correction is very safe or canonical_map explicitly defines the canonical label
</Language-Specific Policy Overview>

<English Normalization Rules>
Apply all of the following to English keywords when safe.

1. Orthographic normalization
- Normalize harmless surface-form variation:
  - repeated spaces
  - leading/trailing spaces
  - spacing inconsistencies
  - punctuation-only variation
  - hyphenation differences
  - slash spacing differences when meaning is unchanged
  - casing inconsistencies
- Examples:
  - self checkout -> Self Checkout
  - self-checkout -> Self Checkout
  - e-mail -> Email
  - email -> Email
  - qr code -> QR Code
  - qr-code -> QR Code

2. Morphological normalization
Normalize inflected word forms to the closest faithful base form when this improves dashboard consistency and does not make the result unnatural.

Allowed:
- plural noun -> singular noun
- comparative adjective -> base adjective
- superlative adjective -> base adjective
- standalone present participle / gerund / past-tense / past-participle action keyword -> lemma/base form

Examples:
- promotions -> Promotion
- vouchers -> Voucher
- prices -> Price
- cheaper -> Cheap
- fastest -> Fast
- waiting -> Wait
- delayed -> Delay only if it is clearly used as a standalone action/event concept

Do NOT force lemma conversion if the keyword is a stable natural phrase.
Examples:
- shipping fee -> Shipping Fee
- loading page -> Loading Page
- damaged product -> Damaged Product
- tracking number -> Tracking Number

3. Phrase-level canonicalization
- Normalize at phrase level, not token-by-token in isolation.
- Prefer the simplest faithful noun-phrase label when possible.
- Preserve meaningful multi-word concepts.
- Examples:
  - push notifications -> Push Notification
  - delayed delivery -> Delivery Delay
  - delivery delay -> Delivery Delay
  - member prices -> Member Price
  - waiting time -> Waiting Time

4. Abbreviation / shorthand / compressed-form expansion
- Expand common abbreviations, shorthand, clipped forms, and compressed forms when meaning is clear from the keyword and original comment.
- Examples:
  - promo code -> Promotional Code
  - promo-code -> Promotional Code
  - promocode -> Promotional Code
  - notif -> Notification
  - qty -> Quantity
  - msg -> Message
  - addr -> Address
- Only expand ambiguous abbreviations when strongly supported by the comment or canonical_map.
- Example:
  - cs -> Customer Service only when clearly supported
- If ambiguous, do not guess.

5. Spelling / typo correction
- Correct only obvious high-confidence typos.
- Use the original comment, canonical_map, and domain_lexicon as evidence if available.
- Examples:
  - promocde -> Promotional Code
  - delviery -> Delivery
  - notfication -> Notification
- If uncertain, do not correct.

6. Proper nouns / brands / official product names
- Preserve official or widely recognized casing.
- Examples:
  - Apple Pay -> Apple Pay
  - apple pay -> Apple Pay
  - PayMe -> PayMe
  - iPhone -> iPhone
  - WhatsApp -> WhatsApp

7. Output formatting
- For generic English phrases, output in Title Case.
- Preserve official casing for brands, technical abbreviations, or product names.
- Examples:
  - promotional code -> Promotional Code
  - push notification -> Push Notification
  - qr code -> QR Code
  - Apple Pay -> Apple Pay

8. No semantic expansion
- Do not make the keyword more specific than the original evidence supports.
- Example:
  - product -> Product
  - NOT Skincare Product unless clearly supported by the comment

9. No semantic drift
- Do not broaden, narrow, or replace the meaning.
- Examples:
  - price tag -> Price Tag
  - NOT Price if the comment clearly refers to labels/tags
  - voucher -> Voucher
  - NOT Promotional Code unless canonical_map explicitly defines them as the same dashboard label

10. Keep valid generic terms if that is all the upstream agent extracted
- If the keyword is generic but valid, normalize only its form.
- Examples:
  - products -> Product
  - promotions -> Promotion
- Do NOT replace it with a more specific term without evidence.
</English Normalization Rules>

<Chinese Normalization Rules>
Apply only conservative cleanup and high-confidence correction.

1. Safe surface cleanup
Allowed:
- remove accidental spaces between Chinese characters
- remove duplicated spaces
- normalize full-width / half-width punctuation and digits when safe
- remove obvious punctuation noise around the keyword
- normalize Simplified/Traditional Chinese to dashboard_chinese_script if such a setting is provided

Examples:
- 優 惠碼 -> 優惠碼
- 推 送 通知 -> 推送通知
- 訂單 狀態 -> 訂單狀態
- 优惠码 -> 優惠碼 if dashboard_chinese_script = zh-Hant
- 優惠碼 -> 优惠码 if dashboard_chinese_script = zh-Hans

2. High-confidence typo / mistaken-character correction
- Correct only obvious typo-like errors when the intended word is strongly supported by:
  a) the original comment,
  b) domain context,
  c) canonical_map, and/or
  d) domain_lexicon.
- This includes accidental wrong characters and very high-confidence mistaken homophone-like characters.
- If there is any real ambiguity, do not correct.

Examples:
- 折扣馬 -> 折扣碼 only if the comment clearly refers to a discount/code context
- 推送通之 -> 推送通知 only if strongly supported by context
- 訂單壯態 -> 訂單狀態 only if strongly supported by context

3. Do NOT freely paraphrase Chinese
- Do NOT rewrite one phrase into a different Chinese phrase unless canonical_map explicitly defines the canonical label.
- Do NOT translate Chinese keywords into English.
- Do NOT aggressively replace synonyms.
- Do NOT infer hidden specificity.

4. Chinese phrase preservation
- Preserve the original Chinese phrase as much as possible after cleanup/correction.
- Do not shorten or rewrite unless the correction is clearly necessary and safe.

5. Mixed-script Chinese keywords
- If a Chinese keyword contains English letters or digits, keep the phrase faithful and only normalize the non-Chinese portion when clearly safe.
- Example:
  - QR code 掃描 -> QR Code 掃描 only if safe and natural
</Chinese Normalization Rules>

<Other Non-English Language Rules>
Apply conservative normalization only.

Allowed:
- trim leading/trailing whitespace
- collapse repeated spaces
- normalize harmless punctuation variation
- normalize obvious hyphenation/spacing variation when safe
- preserve accents/diacritics
- preserve locale-specific spelling and casing conventions as much as possible
- apply canonical_map if provided and safe
- correct only obvious high-confidence typos

Do NOT:
- aggressively lemmatize
- force English-style Title Case if unnatural for that language
- rewrite phrases into English
- guess semantic equivalence across languages unless canonical_map explicitly defines it

If uncertain, make the smallest safe normalization only.
</Other Non-English Language Rules>

<Mixed-Language Handling>
If a keyword mixes multiple languages:
- preserve meaning exactly
- do not freely translate
- normalize only the clearly safe parts
- prefer canonical_map if available
- if unsure, leave the keyword as close to the original as possible
</Mixed-Language Handling>

<Canonical Map Rule>
If canonical_map is provided:
- prefer the mapped canonical form whenever the alias match is exact or clearly intended
- canonical_map may define dashboard-level equivalence beyond raw linguistic normalization
- do not override canonical_map unless it would clearly contradict the original keyword or comment

Examples:
- "promo code" -> "Promotional Code"
- "promocode" -> "Promotional Code"
- "優惠碼" -> "Promotional Code" only if canonical_map explicitly defines this mapping
</Canonical Map Rule>

<Domain Lexicon Rule>
If domain_lexicon is provided:
- use it only as supporting evidence for typo correction and safer canonicalization
- do not force a domain_lexicon term if the original keyword clearly means something else
- prefer the closest faithful term already supported by the comment
</Domain Lexicon Rule>

<If Two Keywords Normalize to the Same Text>
- Do NOT merge keyword entries.
- Keep the same number of keyword objects.
- Only normalize the text field for each entry independently.
</If Two Keywords Normalize to the Same Text>

<Disambiguation Rule>
If a keyword can be normalized in multiple ways, choose the version that:
1) stays closest to the original keyword text,
2) stays faithful to the original comment context,
3) matches canonical_map if provided,
4) is most useful as a stable dashboard label,
5) uses the smallest safe change.

If uncertain, make the smallest safe normalization only.
</Disambiguation Rule>

<What You Must NOT Do>
- Do NOT add new keywords.
- Do NOT remove keywords.
- Do NOT merge keywords.
- Do NOT change keyword sentiment.
- Do NOT change topic text.
- Do NOT change department text.
- Do NOT change overall_sentiment.
- Do NOT change cannot_classified.
- Do NOT invent hidden specificity.
- Do NOT translate keywords unless canonical_map explicitly defines the dashboard canonical label.
- Do NOT aggressively rewrite Chinese.
- Do NOT aggressively rewrite non-English languages using English rules.
</What You Must NOT Do>

<Validation Checklist>
Before returning the JSON:
- Ensure the JSON structure is unchanged except keyword text normalization.
- Ensure keyword count is unchanged.
- Ensure every keyword sentiment is unchanged.
- Ensure topics are unchanged.
- Ensure departments are unchanged.
- Ensure overall_sentiment is unchanged.
- Ensure cannot_classified is unchanged.
- Ensure English keywords use faithful canonical normalized text when safely possible.
- Ensure Chinese keywords are only conservatively cleaned or high-confidence corrected.
- Ensure other languages are only conservatively normalized unless canonical_map safely applies.
- Ensure output is valid JSON only.
</Validation Checklist>

<Output Rules>
- Return only valid JSON.
- No explanations.
- No markdown.
- No extra text.
- Keep the exact same top-level key order as the input JSON.
- Only normalize keyword text where appropriate.
</Output Rules>

<Short Examples>

Input:
comment: "Please add more promo codes."
result_json:
{
  "topics": [
    {"text": "Promotion", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "promo codes", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Promotion", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "Promotional Code", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Input:
comment: "The prices are cheaper now."
result_json:
{
  "topics": [
    {"text": "Pricing", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Trading", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "prices", "sentiment": "positive"},
    {"text": "cheaper", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Pricing", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Trading", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "Price", "sentiment": "positive"},
    {"text": "Cheap", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input:
comment: "I am still waiting for delivery."
result_json:
{
  "topics": [
    {"text": "Delivery", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "waiting", "sentiment": "negative"},
    {"text": "delviery", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Delivery", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Supply Chain", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "Wait", "sentiment": "negative"},
    {"text": "Delivery", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input:
comment: "The waiting time is too long."
result_json:
{
  "topics": [
    {"text": "Queue Experience", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Store Operations", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "waiting", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Queue Experience", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Store Operations", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "Waiting Time", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input:
comment: "The self-checkout area is convenient."
result_json:
{
  "topics": [
    {"text": "Checkout Experience", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Store Operations", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "self-checkout", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Checkout Experience", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "Store Operations", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "Self Checkout", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input:
comment: "希望有更多推送通知。"
result_json:
{
  "topics": [
    {"text": "Order Status Communication", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "CRM", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "推 送 通知", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Order Status Communication", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "CRM", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "推送通知", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Input:
comment: "我想用折扣碼，但系統好似唔得。"
result_json:
{
  "topics": [
    {"text": "Promotion", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "折扣馬", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Promotion", "sentiment": "negative"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "negative"}
  ],
  "keywords": [
    {"text": "折扣碼", "sentiment": "negative"}
  ],
  "overall_sentiment": "negative",
  "cannot_classified": false
}

Input:
comment: "店內好舒服。"
result_json:
{"cannot_classified": true}

Output:
{"cannot_classified": true}

</Short Examples>

<Stop Condition>
- If cannot_classified is true, return the input unchanged.
- Otherwise, return the same JSON with only keyword text normalized where appropriate.
- Never output anything except JSON.
</Stop Condition>
"""

def _normalize_keywords_sync(comment: str, result_json: dict) -> tuple[TotalResponse, dict]:
    content = f"""
    comment: {comment}
    result_json: {json.dumps(result_json, indent=4, ensure_ascii=False, default=str)}
    """
    response = client.chat.completions.create(
        model=NORMALIZE_KEYWORDS_MODEL,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": content}],
        temperature=NORMALIZE_KEYWORDS_TEMPERATURE,
        response_format={"type": "json_object"},
    )
    response_content = response.choices[0].message.content
    print("--------------------------------")
    print(f"Response content for {content}: {response_content}")
    print("--------------------------------")
    if response_content is None:
      # Return empty NormalizeKeywordsResponse when no content
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

def normalize_keywords(comment: str, result_json: dict) -> tuple[TotalResponse, dict]:
    return run_in_threadpool(_normalize_keywords_sync, comment, result_json)
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

system_prompt = """<Role and Objective>
Your task is to normalize keyword text only.

You will receive:
1) the original customer comment, and
2) a JSON object produced by an upstream classifier.

Your job is to normalize the keyword text field in the keywords array while preserving meaning and sentiment.

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
- convert non-Chinese keywords to canonical form where appropriate
- do not introduce new concepts
- do not paraphrase beyond what is supportable from the original comment
</Core Mission>

<Language Handling>
1) For Traditional Chinese (zh-Hant) and Simplified Chinese (zh-Hans):
   - DO NOT normalize.
   - Keep the keyword text exactly unchanged.

2) For languages other than zh-Hant/zh-Hans:
   - Normalize the keyword text into a canonical form when possible.
   - Use the closest faithful base form.
   - Singularize plural nouns by default when meaning is preserved.
   - Keep brand/proper names faithful.
</Language Handling>

<Normalization Rules for Non-Chinese Keywords>
Apply these rules only to non-Chinese keywords:

1. Canonical form
- Prefer the canonical noun-phrase form over the raw surface form.
- If both raw and normalized forms are possible, output the normalized form.

2. Singularization
- Singularize common count nouns when meaning is preserved.
- Examples:
  - promotions -> Promotion
  - vouchers -> Voucher
  - prices -> Price
  - price tags -> Price Tag

3. Lemmatization
- Convert inflected words to their closest faithful base form where appropriate.
- Do not use aggressive stemming.
- Do not invent a word that does not naturally match the source meaning.

4. Phrase-level normalization
- Normalize at phrase level, not token-by-token in isolation.
- Preserve meaningful multi-word phrases when present.

5. Formatting
- Output the final normalized keyword in Upper Camel Case with spaces preserved.
- Examples:
  - self checkout -> Self Checkout
  - apple pay -> Apple Pay
  - promotion stamp card -> Promotion Stamp Card

6. Proper nouns / brands
- Preserve brand or product casing when needed.
- Examples:
  - PayMe -> PayMe
  - iPhone -> iPhone
  - Apple Pay -> Apple Pay

7. No semantic expansion
- Do not make the keyword more specific than the evidence supports.
- Example:
  - products -> Product
  - NOT Skincare Product unless that specificity is already explicit in the original comment

8. No semantic drift
- Do not make the keyword broader or different in meaning.
- Example:
  - price tags -> Price Tag
  - NOT Price if the source clearly refers to price labels/tags

9. Keep valid generic terms if that is all the upstream agent extracted
- If the upstream keyword is generic but still valid for your task, normalize its form rather than replacing its meaning.
- Example:
  - promotions -> Promotion
  - products -> Product
- Do NOT reject or replace simply because it is generic.
</Normalization Rules for Non-Chinese Keywords>

<What You Must NOT Do>
- Do NOT add new keywords.
- Do NOT remove keywords.
- Do NOT merge keywords.
- Do NOT change keyword sentiment.
- Do NOT change topic text.
- Do NOT change department text.
- Do NOT change overall_sentiment.
- Do NOT change cannot_classified.
- Do NOT infer hidden specificity that is not clearly supported by the original comment.
- Do NOT translate the keywords.
- Do NOT normalize Chinese keywords.
</What You Must NOT Do>

<Disambiguation Rule>
If a keyword can be normalized in multiple ways, choose the version that:
1) stays closest to the original keyword text,
2) stays faithful to the original comment,
3) uses the simplest canonical noun-phrase form.

If uncertain, make the smallest safe normalization only.
</Disambiguation Rule>

<Validation>
Before returning the JSON:
- Ensure the JSON structure is unchanged except keyword text normalization.
- Ensure keyword count is unchanged.
- Ensure every keyword sentiment is unchanged.
- Ensure non-Chinese keywords use canonical normalized text when safely possible.
- Ensure Chinese keywords remain unchanged.
- Ensure output is valid JSON only.
</Validation>

<Output Rules>
- Return only valid JSON.
- No explanations.
- No markdown.
- No extra text.
- Keep the exact same top-level key order as the input JSON.
- Only normalize keyword text where appropriate.
</Output Rules>

<Examples>

Input:
comment: "More promotions please and vouchers."
result_json:
{
  "topics": [
    {"text": "Promotion", "sentiment": "neutral"}
  ],
  "departments": [
    {"text": "Marketing", "sentiment": "neutral"},
    {"text": "CRM", "sentiment": "neutral"},
    {"text": "Trading", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "promotions", "sentiment": "neutral"},
    {"text": "vouchers", "sentiment": "neutral"}
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
    {"text": "Marketing", "sentiment": "neutral"},
    {"text": "CRM", "sentiment": "neutral"},
    {"text": "Trading", "sentiment": "neutral"}
  ],
  "keywords": [
    {"text": "Promotion", "sentiment": "neutral"},
    {"text": "Voucher", "sentiment": "neutral"}
  ],
  "overall_sentiment": "neutral",
  "cannot_classified": false
}

Input:
comment: "The products were easy to browse."
result_json:
{
  "topics": [
    {"text": "Website/App Navigation", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "IT", "sentiment": "positive"},
    {"text": "Marketing", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "products", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Output:
{
  "topics": [
    {"text": "Website/App Navigation", "sentiment": "positive"}
  ],
  "departments": [
    {"text": "IT", "sentiment": "positive"},
    {"text": "Marketing", "sentiment": "positive"}
  ],
  "keywords": [
    {"text": "Product", "sentiment": "positive"}
  ],
  "overall_sentiment": "positive",
  "cannot_classified": false
}

Input:
comment: "已下單，但希望可以加多推送通知，等我知道幾時出貨。"
result_json:
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

Input:
comment: "店內好舒服。"
result_json:
{"cannot_classified": true}

Output:
{"cannot_classified": true}

</Examples>

<Stop Condition>
- If cannot_classified is true, return the input unchanged.
- Otherwise, return the same JSON with only keyword text normalized where appropriate.
- Never output anything except JSON.
</Stop Condition>"""

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
import os
import json
from openai import AzureOpenAI, DefaultHttpxClient  
from dotenv import load_dotenv
from models.Survey import Survey
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
# Configs for generate strategy
GENERATE_STRATEGY_MODEL = os.getenv("GENERATE_STRATEGY_MODEL", "gpt-4.1")
GENERATE_STRATEGY_TEMPERATURE = float(os.getenv("GENERATE_STRATEGY_TEMPERATURE", 0.25))
GENERATE_STRATEGY_MAX_TOKENS = int(os.getenv("GENERATE_STRATEGY_MAX_TOKENS", 10000))


def _generate_strategy_sync(data: list[Survey]) -> tuple[str, dict]:
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
    return response_content, response.usage.model_dump()


async def generate_strategy(data: list[Survey]) -> tuple[str, dict]:
    return await run_in_threadpool(_generate_strategy_sync, data)

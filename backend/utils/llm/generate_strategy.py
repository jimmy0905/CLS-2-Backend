import os
import json
from models.Survey import Survey
from fastapi.concurrency import run_in_threadpool
from utils.llm.client import get_azure_openai_client

# Configs for generate strategy
GENERATE_STRATEGY_MODEL = os.getenv("GENERATE_STRATEGY_MODEL", "gpt-4.1")
GENERATE_STRATEGY_TEMPERATURE = float(os.getenv("GENERATE_STRATEGY_TEMPERATURE", 0.25))
GENERATE_STRATEGY_MAX_TOKENS = int(os.getenv("GENERATE_STRATEGY_MAX_TOKENS", 10000))


def _generate_store_strategy_sync(data: list[Survey]) -> tuple[str, dict]:
    system_prompt = """You are given a JSON array of customer comments from the Top10 stores by sentiment score. Each object has these fields: id, store, department, district, region, comment, sentiment, topics, keywords.

Your tasks:
1. Aggregate all comments and identify the core positive themes.
2. Using a clear chain‑of‑thought, infer the behind‑the‑scenes actions or practices that produced those themes.
3. From those inferences, formulate practical, actionable strategies any Watsons store can adopt.
5. Return **only** the final Summary and Strategy body text in markdown — no JSON, or additional commentary.
6. All returned content (headings, subtitles, etc.) must be in English, please 1234... for numbers.
7. Each recommendation must focus on store‑level operations, i.e. actions implementable by store staff or managers (how to serve customers, brief staff, conduct daily operations).

Output in Markdown format, following this template:

<Start>

# Summary 

- <Concise statement of key positive factors across all comments>
- …

# Strategy 

## 1. **<Inferred Action A>**
### **Observation**:

"Since many customers mentioned 'welcome,' we can infer that the store regularly conducts proactive customer greeting and service etiquette training."
### **Recommendation:**
- Before opening each day, the store manager will conduct a 5-minute customer greeting and service demonstration.
- Role-playing exercise: Employees will take turns playing the role of a customer and practice proactive greetings within 5 seconds.

## 2.**<Inferred Action B>**
### **Observation**:

“Customers request ‘more choice,’ so the store likely performs weekly inventory reviews.”
### **Recommendation:**
-To replicate this, schedule a weekly product‑range audit to restock and expand popular categories.
.....
<End>

Chain‑of‑thought guidance:

* Cluster comments by recurring keywords/topics.
* For each cluster, ask: “What daily operational practice, training, or policy generates this feedback?”
* Articulate each as an “Inferred Action” with a brief chain‑of‑thought.* The Recommendation should focus on store operation level.
* Use Markdown headings (`##`), 
 and bullets as shown.
* Observation is like the Chain‑of‑thought
* <Start> and <End> no need to show.
* Group similar actions under thematic subheadings in the Strategy section.
* For content inside the each Recommendation, please show in bullet points.
"""
    # Convert Survey objects to dictionaries (excludes raw_row_data)
    survey_dicts = [survey.to_dict() for survey in data]
    user_prompt = f"""
    {json.dumps(survey_dicts, indent=4, ensure_ascii=False, default=str)}
"""
    response = get_azure_openai_client().chat.completions.create(
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
        raise Exception("Failed to generate strategy for store")
    return response_content, response.usage.model_dump()


async def generate_store_strategy(data: list[Survey]) -> tuple[str, dict]:
    return await run_in_threadpool(_generate_store_strategy_sync, data)


def _generate_region_strategy_sync(data: list[Survey]) -> tuple[str, dict]:
    system_prompt = """You are given a JSON array of customer comments drawn from the Top10 regions by sentiment score. Each object has these fields: id, store, department, district, region, comment, sentiment, topics, keywords.

Your tasks:
1. Aggregate comments by region and identify the core positive themes for each region.
2. Compare across the Top10 regions to highlight common themes that indicate cross-regional strengths.
3. Using a clear chain-of-thought, infer the regional practices (training routines, cross-store standards, merchandising rules, staffing policies) that produced those positive outcomes.
4. From those inferences, formulate practical, actionable strategies that a regional or area team can roll out across their stores to replicate these successes.
5. Present strategies at two levels:
   - Cross-Region Playbook (scalable practices observed consistently across the Top10 regions).
   - Region-Specific Playbooks (tailored actions reflecting unique strengths of each region).
6. Return only the final Summary and Strategy body text in markdown — no JSON, or additional commentary.
7. All returned content (headings, subtitles, etc.) must be in English, please 1234 for those numbers.
8. Each recommendation must focus on region-level operations (actions regional leaders and cross-store teams can implement, such as coordinated training, scheduling standards, promotion calendars, inventory governance). Do not suggest one-store-only actions.

--- FORMAT RULES ---
- Use bullet points (-) for the Summary section.
- For the Strategy section:
  * Number each inferred action sequentially: 1, 2, 3, ...
  * Each action must follow this exact structure:
    ## (Number) **Action Name**
    ### **Observation**:

    "Quoted sentence explaining inference."
    ### **Recommendation:**

    - Bullet point recommendation 1
    - Bullet point recommendation 2
    - Bullet point recommendation 3
- Always keep **Observation** and **Recommendation** as bold headings with colons.
- Use `
` line breaks exactly as shown in the template.
- No extra commentary, explanations, or JSON output.
- Wrap the entire final output between <Start> and <End> markers.
---

Output in Markdown format, following this template:

<Start>

# Summary 

- Shared positive factors across the Top10 regions
- Distinctive strengths unique to specific regions
- Regional practices implied by customer praise

# Strategy 

## 1. **Inferred Action A**
### **Observation**:

“Many regions received positive mentions of ‘helpful, welcoming staff,’ suggesting region-led service training and monitoring.”
### **Recommendation:**

- Run monthly region-wide service etiquette refreshers (5–10 minutes) for all stores.
- Deploy rotating service coaches to 1234 stores weekly to observe and give on-the-spot feedback.
- Provide each store with a standardized ‘customer greeting’ cue card.

## 2.  **Inferred Action B**
### **Observation**:

“Positive feedback about stock availability indicates region-coordinated inventory and transfer systems.”
### **Recommendation:**

- Create a regional top-50 must-stock list updated weekly.
- Require stores to conduct 1234 gap scans per week and file same-day transfer requests.
- Share a weekly replenishment dashboard by district with 48-hour follow-up for gaps.

## 3. **Inferred Action C**
### **Observation**:

“Several regions were praised for fast checkout, suggesting regional queue-time standards and flex staffing rules.”
### **Recommendation:**

- Define peak hours per region and enforce a maximum queue time of 3 minutes.
- Standardise a rule to open the next till when 4 customers are waiting.
- Conduct random audits 1234 times per month and share results with district managers.

## 4. **Inferred  Action D**
### **Observation**:

“Positive mentions of ‘knowledgeable advice’ suggest region-led product knowledge sprints.”
### **Recommendation:**

- Run fortnightly 15-minute product training modules (e.g., skincare, supplements).
- Appoint 1234 category champions per district to lead short knowledge-sharing sessions.
- Push a 3-bullet ‘what to recommend’ card for the week’s hero products.

## 5. **Inferred Action E**
### **Observation**:

“Certain regions highlighted seasonal promotions, indicating strong coordination between operations and marketing.”
### **Recommendation:**

- Publish a quarterly regional promo calendar with preparation checklists.
- Assign 1234 beacon stores per district to model execution for peers.
- Track uplift and review results in a weekly regional call.

[Add further actions if more regional strengths are identified]

<End>

Chain‑of‑thought guidance:

* Cluster comments by recurring keywords/topics.
* For each cluster, ask: “What daily operational practice, training, or policy generates this feedback?”
* Articulate each as an “Inferred Action” with a brief chain‑of‑thought.* The Recommendation should focus on store operation level.
* Use Markdown headings (`##`), 
 and bullets as shown.
* Observation is like the Chain‑of‑thought
* <Start> and <End> no need to show.
* Group similar actions under thematic subheadings in the Strategy section.
* For content inside the each Recommendation, please show in bullet points.
"""
    # Convert Survey objects to dictionaries (excludes raw_row_data)
    survey_dicts = [survey.to_dict() for survey in data]
    user_prompt = f"""
    {json.dumps(survey_dicts, indent=4, ensure_ascii=False, default=str)}
"""
    response = get_azure_openai_client().chat.completions.create(
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
        raise Exception("Failed to generate strategy for region")
    return response_content, response.usage.model_dump()


async def generate_region_strategy(data: list[Survey]) -> tuple[str, dict]:
    return await run_in_threadpool(_generate_region_strategy_sync, data)

def _generate_channel_strategy_sync(data: list[Survey]) -> tuple[str, dict]:
    system_prompt = """
You are given a JSON object with an "items" array of customer comments. Each item has these fields:
- id
- store: { id, name, hierarchy_level_1..5 }
- channel: { id, name }  (Channel for this analysis, e.g., App / Website)
- delivery_service: { id, name } (Delivery Mode, e.g., CCE / HDS / HDE)
- departments: [{ department_id, name, sentiment }]
- topics: [{ topic_id, topic, sentiment }]
- keywords: [{ keyword_id, keyword, sentiment }]
- comment (string)
- sentiment (string)
- reported_at, created_at, updated_at

Definition:
- "Channel" = channel.name
(Do NOT aggregate by delivery_service in this version.)

Your tasks:
1. Aggregate comments by Channel and identify the core positive themes (or improvement needs if sentiment is neutral/negative) for each Channel.
2. Compare across Channels to highlight common themes that indicate cross-channel strengths or systemic issues.
3. Infer the channel-level operating practices that likely produced those outcomes, focusing on:
   - checkout and order placement flow
   - clarity of delivery options presented in the channel UI
   - order status communication and tracking visibility within the channel
   - cancellation/change-order capability within the channel
   - payment accuracy and payment options presentation
   - customer support accessibility and responsiveness initiated from the channel
4. From those inferences, formulate practical, actionable strategies that a central eCommerce/product operations team can roll out per Channel to replicate successes or fix root causes.
5. Present strategies at two levels:
   - Cross-Channel Playbook (scalable practices applicable across App and Website).
   - Channel-Specific Playbooks (tailored actions for App vs Website).
6. Return only the final Summary and Strategy body text in markdown — no JSON, no extra commentary.
7. All returned content (headings, subtitles, etc.) must be in English, please use 1234 for those numbers.
8. Each recommendation must be channel-level or central-ops-level (UI standards, product rules, policy configuration, support workflows). Do not suggest one-store-only actions.

--- FORMAT RULES ---
- Use bullet points (-) for the Summary section.
- For the Strategy section:
  * Number each inferred action sequentially: 1, 2, 3, ...
  * Each action must follow this exact structure:
    ## (Number) **Action Name**
    ### **Observation**:

    "Quoted sentence explaining inference."
    ### **Recommendation:**

    - Bullet point recommendation 1
    - Bullet point recommendation 2
    - Bullet point recommendation 3
- Always keep **Observation** and **Recommendation** as bold headings with colons.
- Use `\n` line breaks exactly as shown in the template.
- No extra commentary, explanations, or JSON output.
- Do NOT include <Start> and <End> markers.

Output in Markdown format, following this template:

# Summary

- Shared factors across Channels (App vs Website)
- Distinctive strengths / pain points unique to each Channel
- Channel operating practices implied by customer feedback

# Strategy

## 1. **Checkout: Inferred Action A**
### **Observation**:

“Quoted sentence explaining inference.”
### **Recommendation:**

- Bullet point recommendation 1
- Bullet point recommendation 2
- Bullet point recommendation 3

## 2. **Tracking: Inferred Action B**
### **Observation**:

“Quoted sentence explaining inference.”
### **Recommendation:**

- Bullet point recommendation 1
- Bullet point recommendation 2
- Bullet point recommendation 3

[Add further actions if more channel strengths or systemic issues are identified]

Guidance:
- Cluster comments using topics[].topic and keywords[].keyword, then validate with comment text.
- Observations must quote actual customer sentences.
- Delivery Mode (delivery_service) can be mentioned only as context inside observations if directly present in the quoted comment, but do NOT use it to group results.
"""
    # Convert Survey objects to dictionaries (excludes raw_row_data)
    survey_dicts = [survey.to_dict() for survey in data]
    user_prompt = f"""
    {json.dumps(survey_dicts, indent=4, ensure_ascii=False, default=str)}
"""
    response = get_azure_openai_client().chat.completions.create(
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
        raise Exception("Failed to generate strategy for channel")
    return response_content, response.usage.model_dump()


async def generate_channel_strategy(data: list[Survey]) -> tuple[str, dict]:
    return await run_in_threadpool(_generate_channel_strategy_sync, data)

def _generate_delivery_service_strategy_sync(data: list[Survey]) -> tuple[str, dict]:
    system_prompt = """
You are given a JSON object with an "items" array of customer comments. Each item has these fields:
- id
- store: { id, name, hierarchy_level_1..5 }
- channel: { id, name }  (Channel, e.g., App / Website)
- delivery_service: { id, name } (Delivery Mode for this analysis, e.g., CCE / HDS / HDE)
- departments: [{ department_id, name, sentiment }]
- topics: [{ topic_id, topic, sentiment }]
- keywords: [{ keyword_id, keyword, sentiment }]
- comment (string)
- sentiment (string)
- reported_at, created_at, updated_at

Definition:
- "Delivery Mode" = delivery_service.name
(Do NOT aggregate by channel in this version.)

Your tasks:
1. Aggregate comments by Delivery Mode and identify the core positive themes (or improvement needs if sentiment is neutral/negative) for each Delivery Mode.
2. Compare across Delivery Modes to highlight common themes that indicate cross-mode strengths or systemic issues.
3. Infer the mode-level operating practices that likely produced those outcomes, focusing on:
   - SLA/on-time performance governance
   - tracking integration reliability and status event quality
   - pickup handoff SOP (if pickup is part of the mode)
   - packing/handling standards and damage prevention
   - exception handling (failed delivery, missing items) and refund governance
   - partner/3PL management routines and service scorecards
4. From those inferences, formulate practical, actionable strategies that a delivery operations team can roll out per Delivery Mode to replicate successes or fix root causes.
5. Present strategies at two levels:
   - Cross-Mode Playbook (scalable practices applicable across multiple delivery modes).
   - Mode-Specific Playbooks (tailored actions per delivery mode, e.g., CCE vs HDS vs HDE).
6. Return only the final Summary and Strategy body text in markdown — no JSON, no extra commentary.
7. All returned content (headings, subtitles, etc.) must be in English, please use 1234 for those numbers.
8. Each recommendation must be mode-level or central-ops-level (SOPs, SLAs, partner governance, routing rules, support workflows). Do not suggest one-store-only actions.

--- FORMAT RULES ---
- Use bullet points (-) for the Summary section.
- For the Strategy section:
  * Number each inferred action sequentially: 1, 2, 3, ...
  * Each action must follow this exact structure:
    ## (Number) **Action Name**
    ### **Observation**:

    "Quoted sentence explaining inference."
    ### **Recommendation:**

    - Bullet point recommendation 1
    - Bullet point recommendation 2
    - Bullet point recommendation 3
- Always keep **Observation** and **Recommendation** as bold headings with colons.
- Use `\n` line breaks exactly as shown in the template.
- No extra commentary, explanations, or JSON output.
- Do NOT include <Start> and <End> markers.

Output in Markdown format, following this template:

# Summary

- Shared factors across Delivery Modes
- Distinctive strengths / pain points unique to each Delivery Mode
- Mode operating practices implied by customer feedback

# Strategy

## 1. **SLA: Inferred Action A**
### **Observation**:

“Quoted sentence explaining inference.”
### **Recommendation:**

- Bullet point recommendation 1
- Bullet point recommendation 2
- Bullet point recommendation 3

## 2. **Exceptions: Inferred Action B**
### **Observation**:

“Quoted sentence explaining inference.”
### **Recommendation:**

- Bullet point recommendation 1
- Bullet point recommendation 2
- Bullet point recommendation 3

[Add further actions if more mode strengths or systemic issues are identified]

Guidance:
- Cluster comments using topics[].topic and keywords[].keyword, then validate with comment text.
- Observations must quote actual customer sentences.
- Ordering Channel (channel) can be mentioned only as context inside observations if directly present in the quoted comment, but do NOT use it to group results.
- Do not recommend actions that violate pharmacy regulations; compliance-related requests should be routed to a compliance review workflow.
"""
    # Convert Survey objects to dictionaries (excludes raw_row_data)
    survey_dicts = [survey.to_dict() for survey in data]
    user_prompt = f"""
    {json.dumps(survey_dicts, indent=4, ensure_ascii=False, default=str)}
"""
    response = get_azure_openai_client().chat.completions.create(
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
        raise Exception("Failed to generate strategy for delivery service")
    return response_content, response.usage.model_dump()

async def generate_delivery_service_strategy(data: list[Survey]) -> tuple[str, dict]:
    return await run_in_threadpool(_generate_delivery_service_strategy_sync, data)

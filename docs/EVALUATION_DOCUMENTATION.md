# Academic Documentation: System Prompts and LLM-as-a-Judge Evaluation

**Document Version:** 1.0  
**Last Updated:** 2026-01-17  
**Authors:** MealAgent Development Team

---

## Table of Contents

1. [Introduction](#1-introduction)
2. [System Prompt Templates](#2-system-prompt-templates)
   - 2.1 [Elysia Core Prompts](#21-elysia-framework-prompts)
   - 2.2 [Elysia Text Processing Prompts](#22-elysia-text-processing-prompts)
   - 2.3 [Elysia Visualization Prompts](#23-elysia-visualization-prompts)
   - 2.4 [Elysia Preprocessing Prompts](#24-elysia-preprocessing-prompts)
   - 2.5 [Elysia Postprocessing Prompts](#25-elysia-postprocessing-prompts)
   - 2.6 [MealAgent Domain-Specific Prompts](#26-mealagent-domain-specific-prompts)
3. [LLM-as-a-Judge Evaluation](#3-llm-as-a-judge-evaluation)
   - 3.1 [Evaluation Prompt Template](#31-evaluation-prompt-template)
   - 3.2 [Evaluation Criteria and Scoring Guidelines](#32-evaluation-criteria-and-scoring-guidelines)
   - 3.3 [Output Schema](#33-output-schema)
4. [Evaluation Use Case Example](#4-evaluation-use-case-example)
   - 4.1 [Input Data](#41-input-data)
   - 4.2 [Prompt Construction](#42-prompt-construction)
   - 4.3 [Evaluation Result](#43-evaluation-result)
   - 4.4 [Workflow Diagram](#44-workflow-diagram)
5. [Multi-Model Evaluation Results](#5-multi-model-evaluation-results)
6. [References](#6-references)

---

## 1. Introduction

This document provides comprehensive academic-style documentation of the prompt templates used in the MealAgent system and its evaluation framework. The system utilizes:

- **Elysia**: A generic agentic framework for orchestrating LLM-based tool selection and execution
- **MealAgent**: A domain-specific Vietnamese meal planning agent built on top of Elysia
- **LLM-as-a-Judge**: An evaluation methodology using LLMs to assess meal plan quality

The documentation covers three main areas:
1. System prompt templates (Elysia and MealAgent)
2. LLM Judge evaluation prompt template
3. A detailed user case demonstrating the evaluation process

---

## 2. System Prompt Templates

### 2.1 Elysia Framework Prompts

The Elysia framework uses DSPy Signatures to define structured prompts. Below are the key prompt templates:

#### 2.1.1 DecisionPrompt (Routing Agent)

**Purpose:** Routes user requests to appropriate tools/actions within the agentic system.

```python
class DecisionPrompt(dspy.Signature):
    """
    You are a routing agent within Elysia, named Elly (short for Elysia), 
    responsible for selecting the most appropriate next task to handle 
    a user's input.
    Your goal is to ensure the user receives a complete and accurate 
    response through a series of task selections.
    You also respond to the user.

    Core Decision Process:
    1. Analyze the user's input prompt and available tasks
    2. Review completed tasks and their outcomes in previous_reasoning
    3. Check if current information satisfies the input prompt
    4. Select the most appropriate next task from available_tasks
    5. Determine if all possible actions have been exhausted

    Decision Rules:
    - Always select from available_tasks list only
    - Prefer tasks that directly progress toward answering the input prompt
    - Consider tree_count to avoid repetitive decisions
    - IMPORTANT (freshness): If the user asks about pantry/inventory, 
      you MUST route to the pantry branch/tool to re-read current pantry 
      state from the database, even if the conversation history previously 
      said the pantry was empty.
    """
```

**Input Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `instruction` | `str` | Specific guidance for this decision point |
| `tree_count` | `str` | Current attempt number as "X/Y" |
| `available_actions` | `list[dict]` | List of possible actions with function_name, description, future, inputs |
| `unavailable_actions` | `list[dict]` | Actions currently unavailable with availability criteria |
| `successive_actions` | `str` | Nested action tree showing future possibilities |
| `previous_errors` | `list[dict]` | Errors from previous actions to avoid |

**Output Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `function_name` | `str` | Selected function from available_actions |
| `function_inputs` | `dict` | Inputs for the selected function |
| `end_actions` | `bool` | Whether to cease actions after this task |

---

#### 2.1.2 QueryCreatorPrompt (Database Query Builder)

**Purpose:** Converts natural language questions into structured Weaviate queries.

```python
class QueryCreatorPrompt(dspy.Signature):
    """
    You are a database query builder. Your task is to convert natural 
    language questions into structured queries using the provided 
    schema information.

    Instructions:
    1. Carefully read the user's question and the schema details.
    2. Formulate clear, precise queries that best address the user's request.
    3. If the user's question is missing important search terms, use your 
       knowledge to identify and include what should be searched.
    4. You may create multiple queries for the same collection if needed.
    5. Write all your reasoning in the provided reasoning fields.
    6. Return a list of QueryOutput objects that fully satisfy the request.
    7. Each query operates on the entire collection, not a subset from 
       previous steps.
    8. Do not write any code—just provide the correct arguments.
    """
```

**Supported Filter Types:**
- `IntegerPropertyFilter`: For integer comparisons (=, !=, <, >, <=, >=)
- `FloatPropertyFilter`: For float comparisons
- `TextPropertyFilter`: For text equality or pattern matching (LIKE with ?, *)
- `BooleanPropertyFilter`: For boolean comparisons
- `DatePropertyFilter`: For date comparisons
- `ListPropertyFilter`: For list operations (CONTAINS_ANY, CONTAINS_ALL, IS_NULL)

---

#### 2.1.3 AggregationPrompt (Statistical Aggregation)

**Purpose:** Builds aggregation queries for statistical analysis on Weaviate databases.

```python
class AggregationPrompt(dspy.Signature):
    """
    You are a database query builder specializing in converting natural 
    language questions into structured aggregation queries for Weaviate.
    
    Aggregation Operations:
    - integer_property_aggregation: MIN, MAX, MEAN, MEDIAN, MODE, SUM
    - text_property_aggregation: TOP_OCCURRENCES
    - boolean_property_aggregation: TOTAL_TRUE, TOTAL_FALSE, PERCENTAGE_TRUE
    - date_property_aggregation: MIN, MAX, MEAN, MEDIAN, MODE
    
    Supports recursive FilterBucket nesting for complex logical expressions 
    like (A AND B) OR (C AND D).
    """
```

---

#### 2.1.4 FollowUpSuggestionsPrompt

**Purpose:** Generates engaging follow-up questions based on user interactions.

```python
class FollowUpSuggestionsPrompt(dspy.Signature):
    """
    Expert at suggesting engaging follow-up questions based on recent 
    user interactions.
    Generate questions that showcase system capabilities and maintain 
    user interest.
    Questions should be fun, creative, and designed to impress.

    Since you are suggesting _follow-up_ questions, you should not suggest 
    questions that are too similar to the user's prompt.
    Instead, try to think of something that can connect different data 
    sources together, or provide new insights the user may not have 
    thought of.
    """
```

---

#### 2.1.5 TitleCreatorPrompt

**Purpose:** Creates meaningful titles for conversations.

```python
class TitleCreatorPrompt(dspy.Signature):
    """
    You are an expert at creating a title for a given conversation.
    The conversation could be a single user prompt, or a series of 
    user prompts and assistant responses.
    Create a meaningful but punctual title for the conversation.
    """

    conversation: list[dict] = dspy.InputField(
        description="The conversation with role and content keys."
    )
    title: str = dspy.OutputField(
        description="A single, short, succinct summary (no more than 10 words)."
    )
```

---

### 2.2 Elysia Text Processing Prompts

#### 2.2.1 CitedSummarizingPrompt

**Purpose:** Summarizes retrieved data with proper citation references.

```python
class CitedSummarizingPrompt(dspy.Signature):
    """
    Given a user_prompt, as well as a list of retrieved objects from the environment, 
    summarize the information in the objects to answer the user's prompt.
    Your output will be a collection of TextWithCitation objects that form a 
    complete summary when combined.
    
    Do not list any of the retrieved objects in your response. 
    Your summary should be parsing the retrieved objects, and summarising 
    the information in them that is relevant to the user's prompt.
    You should provide useful analysis, new information via analysing the 
    existing objects, and synthesising the information.
    """

    subtitle = dspy.OutputField(description="A subtitle for the summary")
    cited_text: List[TextWithCitation] = dspy.OutputField(
        description="""
        A list of TextWithCitation objects whose 'text' fields will be 
        concatenated to form the complete summary.
        
        CITATION RULES:
        1. NEVER include reference IDs in the 'text' field itself
        2. ALWAYS copy reference IDs exactly from the source's _REF_ID to the ref_ids list
        3. Keep the text clean and reference-free
        """
    )
```

---

#### 2.2.2 SummarizingPrompt

**Purpose:** Summarizes retrieved objects without citations.

```python
class SummarizingPrompt(dspy.Signature):
    """
    Given a user_prompt, as well as a list of retrieved objects, summarize 
    the information in the objects to answer the user's prompt.
    
    Information about you:
    - You are a chatbot for an app named Elysia.
    - You are a helpful assistant designed to be used in a chat interface.
    - Your primary task is to summarize the information in the retrieved objects.
    
    Do not list any of the retrieved objects in your response.
    """

    subtitle = dspy.OutputField(description="A subtitle for the summary")
    summary = dspy.OutputField(
        description="The summary of retrieved objects using markdown formatting."
    )
```

---

#### 2.2.3 TextResponsePrompt

**Purpose:** Generates helpful text responses to user queries.

```python
class TextResponsePrompt(dspy.Signature):
    """
    You are a helpful assistant, designed to be used in a chat interface 
    and respond to user's prompts in a helpful, friendly, and polite manner.
    
    Your response should be informal, polite, and assistant-like.
    
    If there is an error and you could not complete a task, use this tool 
    to suggest a brief reason why. For example:
    - If there is a missing API key, inform the user to add it to settings
    - If you cannot connect to weaviate, the user needs to input API keys
    - If there are no collections available, the user needs to analyze in 'data' tab
    """

    response = dspy.OutputField(
        description="The response to the user's prompt with suggestions if needed."
    )
```

---

### 2.3 Elysia Visualization Prompts

#### 2.3.1 CreateBarChart

**Purpose:** Creates bar charts from data.

```python
class CreateBarChart(dspy.Signature):
    """
    Create one or more bar charts.
    - Maximum of 9 bar charts
    - Each bar chart should have a maximum of 10 categories
    - Pick the most relevant categories and values
    """

    charts: list[BarChart] = dspy.OutputField(description="The bar chart to create.")
    overall_title: str = dspy.OutputField(
        description="Overall title for above the grid if multiple charts."
    )
```

---

#### 2.3.2 CreateHistogramChart

**Purpose:** Creates histogram charts from data.

```python
class CreateHistogramChart(dspy.Signature):
    """
    Create one or more histogram charts.
    - Maximum of 9 histogram charts
    - Do not produce more than 50 values per histogram chart
    """

    charts: list[HistogramChart] = dspy.OutputField(description="The histogram chart.")
    overall_title: str = dspy.OutputField(description="Overall title for the grid.")
```

---

#### 2.3.3 CreateScatterOrLineChart

**Purpose:** Creates scatter or line charts from data.

```python
class CreateScatterOrLineChart(dspy.Signature):
    """
    Create one or more scatter or line charts.
    - Maximum of 9 charts
    - Maximum of 50 points per chart
    - Can have multiple y-axis values with different labels
    - Can combine line chart with scatter chart
    """

    charts: list[ScatterOrLineChart] = dspy.OutputField(description="The chart.")
    overall_title: str = dspy.OutputField(description="Overall title for the grid.")
```

---

### 2.4 Elysia Preprocessing Prompts

#### 2.4.1 CollectionSummariserPrompt

**Purpose:** Provides summaries of datasets for data analysis.

```python
class CollectionSummariserPrompt(dspy.Signature):
    """
    You are an expert data analyst who provides summaries of datasets.
    Your task is to provide a summary of the data. This should be concise, 
    one paragraph maximum and no more than 5 sentences.
    Do not calculate any statistics such as length, just describe the data.
    Use markdown formatting to make the summary more readable.
    """

    sample_size = dspy.InputField(
        description="Number of objects in sample out of total collection."
    )
    data_sample = dspy.InputField(
        description="A subset of the data (list of JSON objects)."
    )
    data_fields = dspy.InputField(
        description="The fields that exist in the data."
    )
    overall_summary: str = dspy.OutputField(description="Overall summary paragraph.")
    relationships: str = dspy.OutputField(description="Field relationships (2-4 sentences).")
    structure: str = dspy.OutputField(description="Dataset structure overview (1-3 sentences).")
    irregularities: str = dspy.OutputField(description="Any irregularities found.")
    field_descriptions: dict[str, str] = dspy.OutputField(description="Field name to description mapping.")
```

---

#### 2.4.2 ReturnTypePrompt

**Purpose:** Determines appropriate return types for collection data.

```python
class ReturnTypePrompt(dspy.Signature):
    """
    You are an expert at determining the type of data in a collection.
    Given some possible return types, you should choose the most appropriate 
    ones for this data based on data fields and collection summary.
    """

    collection_summary = dspy.InputField(desc="A description of the collection.")
    data_fields = dspy.InputField(desc="The fields and their data types.")
    example_objects = dspy.InputField(desc="Example objects to understand the data.")
    possible_return_types = dspy.InputField(desc="Return types to choose from.")
    return_types: list[str] = dspy.OutputField(
        desc="All different types of return types that would suit this data."
    )
```

---

#### 2.4.3 DataMappingPrompt

**Purpose:** Maps input data fields to existing field names.

```python
class DataMappingPrompt(dspy.Signature):
    """
    You are an expert at mapping data fields to existing field names.
    """

    mapping_type: str = dspy.InputField(
        desc="Type of mapping: 'conversation', 'message', 'ticket', 'product', 'document', 'table', 'generic'."
    )
    input_data_fields: list[str] = dspy.InputField(desc="Input fields to map.")
    output_data_fields: list[str] = dspy.InputField(desc="Output fields to map to.")
    input_data_types: dict[str, str] = dspy.InputField(desc="Data types of input fields.")
    collection_information: dict = dspy.InputField(desc="Collection metadata including name, length, summary, fields.")
    example_objects: list[dict] = dspy.InputField(desc="Example objects.")
    field_mapping: dict[str, str] = dspy.OutputField(
        desc='Mapping dict e.g. {"title": "name", ...}. Empty string if no mapping.'
    )
```

---

#### 2.4.4 PromptSuggestorPrompt

**Purpose:** Suggests useful prompts for querying a data collection.

```python
class PromptSuggestorPrompt(dspy.Signature):
    """
    You are an expert at suggesting prompts for a given data collection.
    """

    collection_information: dict = dspy.InputField(
        desc="Collection info: name, length, summary, fields with groups/mean/range/type."
    )
    example_objects: list[dict] = dspy.InputField(desc="Example objects.")
    prompt_suggestions: list[str] = dspy.OutputField(
        desc="""
        10 prompts (5-10 words each) that would be useful for querying the data.
        Show actual understanding of the data, not just generic questions.
        Look for interactions between fields and connections the user may not see.
        """
    )
```

---

### 2.5 Elysia Postprocessing Prompts

#### 2.5.1 ObjectSummaryPrompt

**Purpose:** Summarizes individual objects in a list.

```python
class ObjectSummaryPrompt(dspy.Signature):
    """
    Given a list of objects (dictionaries), provide a list of strings 
    where each string is a summary of the object.
    These objects can be of any type, and you should summarise them 
    in a way that is useful to the user.
    """

    objects: list[dict] = dspy.InputField(desc="The objects to summarise.")
    summaries: list[str] = dspy.OutputField(
        desc="""
        Extremely concise summaries of each individual object - what it is, 
        what it is about. A few sentences at most per object.
        """
    )
```

---

### 2.6 MealAgent Domain-Specific Prompts

#### 2.6.1 MealParseSignature (Meal Logging)

**Purpose:** Parses free-text meal descriptions into structured data for logging.

```python
class MealParseSignature(dspy.Signature):
    """Parse meal description to dish name, ingredients array, and portion size."""

    meal_description = dspy.InputField(
        desc="Free-text meal description with dish name and ingredients."
    )
    dish = dspy.OutputField(desc="Dish name/title.")
    ingredients = dspy.OutputField(
        desc="List of objects: name, amount (number), unit (string)."
    )
    portion_size = dspy.OutputField(desc="Number of portions/servings (float).")
```

**Usage Context:** Used in `log_meal_e2e_tool` to convert user's natural language meal descriptions (e.g., "Phở bò với rau sống") into structured data for nutrition calculation.

---

#### 2.6.2 TranslationPrompt (Ingredient Translation)

**Purpose:** Translates Vietnamese ingredient names to English for FDC lookup.

```python
class TranslationPrompt(dspy.Signature):
    """
    Translate Vietnamese ingredient names to English and extract quantity/unit 
    when present.
    Output a list of objects with fields: vn, en, quantity, unit.
    """

    ingredients_vn = dspy.InputField(description="Array of Vietnamese ingredient strings.")
    message_update = dspy.OutputField(description="One-sentence update on translation progress.")
    translations = dspy.OutputField(
        description="List of translated objects with vn, en, quantity, unit."
    )
```

**Usage Context:** Used in `calculate_recipe_macros_tool` to translate Vietnamese ingredients (e.g., "200g thịt bò") to English for matching with the FDC (FoodData Central) database.

---

#### 2.6.3 MacroEstimateSignature (Nutrition Estimation)

**Purpose:** LLM-based fallback for estimating macros when FDC lookup fails.

```python
class MacroEstimateSignature(dspy.Signature):
    """
    Given a Vietnamese dish and its ingredients, estimate realistic 
    nutrition per serving.

    Return a JSON-like object with numeric fields:
      - kcal: total kilocalories per serving
      - protein_g: grams of protein per serving
      - fat_g: grams of fat per serving
      - carb_g: grams of carbohydrates per serving

    Be conservative and avoid extreme values; use typical Vietnamese 
    home-cooking portions.
    """

    dish_name = dspy.InputField(description="Name of the dish (Vietnamese).")
    servings = dspy.InputField(description="Number of servings for the recipe.")
    ingredients = dspy.InputField(description="List of ingredients with rough quantity and unit.")
    reasoning = dspy.OutputField(description="Short explanation of how macros were estimated.")
    macros = dspy.OutputField(
        description='Estimated macros per serving as: {"kcal": float, "protein_g": float, "fat_g": float, "carb_g": float}'
    )
```

**Usage Context:** Used as a fallback in `calculate_recipe_macros_tool` when ingredients cannot be matched to FDC database entries.

---

#### 2.6.4 RecipeMetadataSignature (Dietary Metadata Extraction)

**Purpose:** Extracts dietary metadata (diet types, allergens, devices) from recipes.

```python
class RecipeMetadataSignature(dspy.Signature):
    """
    Extract dietary metadata from a Vietnamese recipe.
    
    Respond with:
      - diet_type: List of applicable diet types 
        (e.g., ["vegetarian", "vegan", "keto", "paleo", "halal", "kosher", "gluten-free", "dairy-free", "none"])
      - allergens: List of allergens present 
        (e.g., ["peanuts", "tree_nuts", "dairy", "eggs", "fish", "shellfish", "soy", "wheat", "sesame", "none"])
      - devices: List of required cooking devices 
        (e.g., ["oven", "stovetop", "microwave", "blender", "food_processor", "air_fryer", "pressure_cooker", "none"])
    
    Use lowercase, underscore-separated values. Return "none" if no applicable items.
    """

    dish_name = dspy.InputField(description="Vietnamese dish name.")
    ingredients = dspy.InputField(description="List of ingredients (truncated for efficiency).")
    cooking_method = dspy.InputField(description="Cooking methods used.")
    diet_type = dspy.OutputField(description='JSON array of diet types.')
    allergens = dspy.OutputField(description='JSON array of allergens.')
    devices = dspy.OutputField(description='JSON array of required devices.')
```

**Usage Context:** Used in `precompute_recipe_macros.py` script to enrich Recipe records with dietary constraints and equipment requirements.

---

#### 2.6.5 MealDraftSignature (Meal Planning)

**Purpose:** Generates Vietnamese meal suggestions for a specific meal slot.

```python
class MealDraftSignature(dspy.Signature):
    """Generate 4-8 Vietnamese meal suggestions for a specific meal slot.

    The model MUST:
    - Return a JSON ARRAY (not a wrapped object) of 4-8 suggestions.
    - Each suggestion is an object with fields:
      dish_name, general_term, role, meal_type, category.
    - Respect dietary constraints (diet_type), allergens and health goal.
    """

    meal_slot = dspy.InputField(
        desc="Meal slot: 'breakfast', 'lunch', or 'dinner'."
    )
    meal_history = dspy.InputField(
        desc="Recently used dish names to AVOID repeating."
    )
    constraints = dspy.InputField(
        desc="JSON string with dietary constraints: diet_types, exclude_allergens, goal."
    )
    suggestions = dspy.OutputField(
        desc="JSON ARRAY of 4-8 meal suggestion objects."
    )
```

**Full Prompt Example (Vietnamese):**

```
Bạn là chuyên gia ẩm thực Việt Nam. Đề xuất 4-8 món ăn cho bữa {meal_slot}.

## ⚠️ QUAN TRỌNG - ƯU TIÊN MÓN ĂN VIỆT NAM:
- PHẢI ưu tiên các món ăn Việt Nam 
- Chỉ đề xuất món Tây/ngoại nếu không có món Việt phù hợp
- Tên món PHẢI bằng tiếng Việt (VD: "Phở bò", "Cơm trắng", "Thịt kho tàu")

## QUY TẮC:
1. **Số lượng**: TỪ 4 ĐẾN 8 món
2. **Format**: JSON array trực tiếp [...] chứa các OBJECT
3. **Fields bắt buộc**:
   - dish_name: Tên món bằng tiếng Việt
   - general_term: Tên không dấu, dùng dấu gạch ngang
   - role: "breakfast" | "carb" | "main" | "vegetable" | "fruit"
   - meal_type: "{meal_slot}"
   - category: "rice" | "noodle" | "soup" | "bread" | "bakery" | "main_dish" | "vegetable" | "fruit"
```

---

#### 2.6.6 MacroAuditSignature (Nutrition Validation)

**Purpose:** Validates and corrects pre-calculated macros using LLM knowledge.

```python
class MacroAuditSignature(dspy.Signature):
    """
    Review whether the provided macros per serving are realistic for the dish.

    Respond with:
      - verdict: "ok" if macros look reasonable, otherwise "adjust".
      - reason: short explanation (<= 2 sentences).
      - macros_adjusted: JSON object with fields kcal, protein_g, fat_g, carb_g 
        (per serving) if verdict == "adjust".
    """

    dish_name = dspy.InputField(description="Vietnamese dish name.")
    servings = dspy.InputField(description="Number of servings the recipe yields.")
    ingredients = dspy.InputField(description="List of ingredients with quantities.")
    macros = dspy.InputField(
        description="Existing macros per serving (kcal, protein_g, fat_g, carb_g)."
    )
    cooking_notes = dspy.InputField(
        description="Cooking method or notable preparation details."
    )
    verdict = dspy.OutputField(description='Either "ok" or "adjust".')
    reason = dspy.OutputField(description="Short justification of the verdict.")
    macros_adjusted = dspy.OutputField(
        description="JSON string with revised macros if verdict == 'adjust'."
    )
```

**Usage Context:** Used in `validate_recipe_macros.py` script to audit and correct nutrition data that may have been incorrectly calculated by the FDC lookup process.

---

#### 2.6.7 MacroAuditBatchSignature (Batch Nutrition Validation)

**Purpose:** Validates multiple recipes in a single LLM call for efficiency.

```python
class MacroAuditBatchSignature(dspy.Signature):
    """
    Review whether the provided macros per serving are realistic for each recipe.

    CRITICAL: All macros must be calculated and returned PER SINGLE SERVING, 
    not for the entire recipe. The "servings" field indicates how many servings 
    the recipe makes, but macros_per_serving and macros_adjusted must always 
    represent nutrition for ONE serving only.

    You are given a list of recipes. For *each* recipe:
      - If macros_per_serving look reasonable and are present, mark verdict "ok".
      - If macros_per_serving look wrong OR are missing/invalid, mark verdict 
        "adjust" and provide corrected macros_per_serving PER SINGLE SERVING.

    STRICT RESPONSE FORMAT:
      - Respond with a single JSON array (no surrounding text, no comments).
      - Each element MUST be an object:
          {
            "id": "<the id from input>",
            "verdict": "ok" | "adjust",
            "reason": "<short explanation>",
            "macros_adjusted": {"kcal": <number>, "protein_g": <number>, ...}
          }
    """

    recipes = dspy.InputField(
        description="JSON array of recipes with id, dish_name, servings, ingredients, "
                    "cooking_notes, macros_per_serving."
    )
    batch_result_json = dspy.OutputField(
        description="STRICT JSON array with validation results for each recipe."
    )
```

**Usage Context:** Used in `validate_recipe_macros.py` for batch validation, significantly reducing LLM API calls and improving throughput.

---

## 3. LLM-as-a-Judge Evaluation

### 3.1 Evaluation Prompt Template

The LLM Judge evaluates meal plans using a comprehensive prompt that establishes the LLM as a nutrition expert. The full prompt template is shown below:

```python
EVALUATION_PROMPT_TEMPLATE = """
Bạn là một chuyên gia dinh dưỡng rất tích cực và khuyến khích. 
Hãy đánh giá meal plan sau đây với tinh thần tìm kiếm và ghi nhận 
những điểm tốt, cho điểm cao khi có thể.

{user_profile_text}

{meal_plan_text}

=== YÊU CẦU ĐÁNH GIÁ ===

Hãy đánh giá meal plan trên 4 tiêu chí (mỗi tiêu chí 0-100 điểm) 
với nguyên tắc: **ƯU TIÊN CHO ĐIỂM CAO, CHỈ CHO ĐIỂM THẤP KHI THỰC SỰ CẦN THIẾT**.

**Nguyên tắc chung (RẤT QUAN TRỌNG)**: 
- Đa số meal plans thực tế đều có điểm tích cực → hãy coi **70-85 là vùng điểm "bình thường / tốt"**.
- Baseline điểm nên từ **70-80** cho mỗi tiêu chí (trừ khi có vấn đề rõ ràng).
- Cho điểm 80-100 (Excellent) nếu plan tốt hoặc có thể cải thiện dễ dàng.
- Cho điểm 70-80 (Good) nếu plan ổn, không có lỗi nghiêm trọng.
- Cho điểm 60-70 (Fair) chỉ khi có vấn đề nhưng vẫn có thể chấp nhận.
- Chỉ cho điểm <60 (Poor) khi có vấn đề nghiêm trọng.
"""
```

### 3.2 Evaluation Criteria and Scoring Guidelines

The evaluation uses four criteria, each scored from 0-100:

#### 3.2.1 Nutrition (Dinh dưỡng)

| Score Range | Description |
|-------------|-------------|
| **85-100** | Tổng thể khá gần mục tiêu, hoặc có ít nhất 2-3 macro gần mục tiêu |
| **75-85** | Có một số sai lệch nhưng vẫn hợp lý, ít nhất 1 macro gần mục tiêu |
| **65-75** | Có sai lệch nhưng không quá nghiêm trọng, vẫn có điểm tích cực |
| **<65** | Sai lệch rất nghiêm trọng (calo gấp đôi/giảm một nửa, protein <50% mục tiêu) |

#### 3.2.2 Variety (Đa dạng)

| Score Range | Description |
|-------------|-------------|
| **85-100** | Có sự đa dạng rõ ràng, ít nhất 2-3 món khác nhau trong ngày |
| **75-85** | Có sự thay đổi giữa các bữa, ít nhất 2 món khác nhau |
| **65-75** | Có một số lặp lại nhưng vẫn có sự khác biệt |
| **<65** | Gần như hoàn toàn giống nhau, không có sự đa dạng |

#### 3.2.3 Balance (Cân bằng)

| Score Range | Description |
|-------------|-------------|
| **85-100** | Phân bổ hợp lý giữa các bữa, cấu trúc rõ ràng với 3 bữa chính |
| **75-85** | Có cấu trúc cơ bản, các bữa không quá chênh lệch |
| **65-75** | Có một số lệch (bữa tối hơi nặng hơn) nhưng chấp nhận được |
| **<65** | Hoàn toàn mất cân bằng nghiêm trọng |

#### 3.2.4 Feasibility (Tính khả thi)

| Score Range | Description |
|-------------|-------------|
| **85-100** | Các món quen thuộc, nguyên liệu dễ tìm, cách nấu đơn giản |
| **75-85** | Có thể thực hiện được, một vài món hơi phức tạp |
| **65-75** | Có thách thức nhưng người dùng vẫn có thể làm được nếu cố gắng |
| **<65** | Không thực tế với người dùng bình thường |

---

### 3.3 Output Schema

The LLM Judge must return a strictly formatted JSON response:

```json
{
    "overall_score": <float 0-100>,
    "nutrition_score": <float 0-100>,
    "variety_score": <float 0-100>,
    "balance_score": <float 0-100>,
    "feasibility_score": <float 0-100>,
    "feedback": "<nhận xét tổng quan bằng tiếng Việt, 2-3 câu>",
    "strengths": [
        "<điểm mạnh 1>",
        "<điểm mạnh 2>",
        "<điểm mạnh 3>"
    ],
    "suggestions": [
        "<gợi ý cải thiện 1>",
        "<gợi ý cải thiện 2>",
        "<gợi ý cải thiện 3>"
    ]
}
```

**Key Constraints:**
- All scores must be float values from 0-100
- Feedback, strengths, and suggestions must be in Vietnamese
- No markdown code blocks, comments, or extra text
- No trailing commas
- No additional fields beyond those specified

---

## 4. Evaluation Use Case Example

This section provides a complete example of the evaluation process, demonstrating the input data, prompt construction, and resulting evaluation.

### 4.1 Input Data

#### User Profile

```json
{
  "user_id": "b26875a4-0fca-4eba-afa4-bee3de998bd6",
  "age": 23,
  "gender": "male",
  "activity_level": "moderate",
  "dietary_preferences": [],
  "allergies": [],
  "tdee_kcal": 2849.0,
  "protein_g": 150.0,
  "carb_g": 384.3,
  "fat_g": 79.2
}
```

#### Meal Plan

```json
{
  "plan_id": "b26875a4-0fca-4eba-afa4-bee3de998bd6_plan_19b23cf9e639",
  "plan_type": "day",
  "plan_date": "2026-01-10T00:00:00+00:00",
  "total_macros": {
    "kcal": 1734.36,
    "protein_g": 94.01,
    "carb_g": 211.50,
    "fat_g": 62.39
  },
  "meals": {
    "breakfast": {
      "recipe": {"dish_name": "Phở Bò Tái Bò Viên", "food_id": "2400"},
      "servings": 1.0,
      "macros": {"kcal": 804.60, "protein_g": 24.41, "fat_g": 25.51, "carb_g": 121.59}
    },
    "lunch": {
      "recipe": {"dish_name": "Bò Nhúng Giấm", "food_id": "1622"},
      "servings": 1.0,
      "macros": {"kcal": 400.0, "protein_g": 35.0, "fat_g": 10.0, "carb_g": 50.0}
    },
    "dinner": {
      "recipe": {"dish_name": "Cơm gạo lức trộn rau củ", "food_id": "259"},
      "servings": 4.0,
      "accompaniments": [
        {"dish_name": "Thăn heo cuộn nhân Jambon phô mai", "food_id": "1135", "servings": 1.0}
      ],
      "macros": {"kcal": 529.76, "protein_g": 34.6, "fat_g": 26.88, "carb_g": 39.91}
    }
  }
}
```

---

### 4.2 Prompt Construction

The evaluation prompt is constructed by combining:

1. **User Profile Text:**
```
=== USER PROFILE ===

User ID: b26875a4-0fca-4eba-afa4-bee3de998bd6

Mục tiêu dinh dưỡng:
  - Calories: 2849 kcal
  - Protein: 150.0 g
  - Carb: 384.3 g
  - Fat: 79.2 g

Tuổi: 23
Giới tính: male
Mức độ hoạt động: moderate
```

2. **Meal Plan Text:**
```
=== MEAL PLAN (DAY) ===

Tổng dinh dưỡng:
  - Calories: 1734 kcal
  - Protein: 94.0 g
  - Carb: 211.5 g
  - Fat: 62.4 g

Các bữa ăn:

BREAKFAST:
  - Phở Bò Tái Bò Viên (x1.0)
    → 805 kcal, P: 24.4g, C: 121.6g, F: 25.5g

LUNCH:
  - Bò Nhúng Giấm (x1.0)
    → 400 kcal, P: 35.0g, C: 50.0g, F: 10.0g

DINNER:
  - Cơm gạo lức trộn rau củ (x4.0)
    → 530 kcal, P: 34.6g, C: 39.9g, F: 26.9g
  - Thăn heo cuộn nhân Jambon phô mai (x1.0) [accompaniment]
```

3. **Evaluation Instructions** (as shown in Section 3.1)

---

### 4.3 Evaluation Result

The LLM Judge (Google Gemini 3 Flash Preview) produced the following evaluation:

```json
{
  "overall_score": 78.5,
  "nutrition_score": 72.0,
  "variety_score": 85.0,
  "balance_score": 75.0,
  "feasibility_score": 82.0,
  "feedback": "Kế hoạch ăn uống có cấu trúc tốt với các món ăn Việt Nam truyền thống và lành mạnh. Mặc dù tổng năng lượng còn thấp hơn mục tiêu, nhưng các món ăn được chọn lọc rất chất lượng và dễ thực hiện.",
  "strengths": [
    "Sử dụng thực phẩm lành mạnh như gạo lức và thịt thăn heo",
    "Các món ăn quen thuộc, dễ tìm mua hoặc chế biến",
    "Tỷ lệ các nhóm chất trong từng món ăn khá cân bằng"
  ],
  "suggestions": [
    "Tăng thêm khẩu phần cơm hoặc bún để đạt mục tiêu năng lượng",
    "Bổ sung thêm 1-2 bữa phụ nhẹ như trái cây hoặc sữa hạt",
    "Thêm rau xanh vào bữa sáng để tăng cường chất xơ"
  ],
  "metadata": {
    "user_id": "b26875a4-0fca-4eba-afa4-bee3de998bd6",
    "plan_id": "b26875a4-0fca-4eba-afa4-bee3de998bd6_plan_19b23cf9e639",
    "source": "MealPlan",
    "plan_type": "day",
    "plan_date": "2026-01-10T00:00:00+00:00"
  },
  "plan_details": {
    "target_macros": {
      "kcal": 2849.0,
      "protein_g": 150.0,
      "carb_g": 384.3,
      "fat_g": 79.2
    },
    "actual_macros": {
      "kcal": 1734.36,
      "protein_g": 94.01,
      "carb_g": 211.50,
      "fat_g": 62.39
    },
    "macro_differences": {
      "kcal": -1114.64,
      "protein_g": -55.99,
      "carb_g": -172.80,
      "fat_g": -16.81
    }
  }
}
```

#### Analysis of Scores:

| Criterion | Score | Justification |
|-----------|-------|---------------|
| **Nutrition** | 72.0 | Calories are ~39% below target (1734 vs 2849 kcal), protein ~37% below. However, the plan structure allows easy adjustment. |
| **Variety** | 85.0 | Three distinct Vietnamese dishes across meals (Pho, Bo Nhung Dam, Com Gao Luc), good regional diversity. |
| **Balance** | 75.0 | Clear 3-meal structure, but breakfast is calorie-heavy relative to other meals. |
| **Feasibility** | 82.0 | All dishes are traditional Vietnamese, easy to prepare or purchase, familiar ingredients. |
| **Overall** | 78.5 | Weighted average reflecting a "Good" plan with room for improvement in portions. |

---

### 4.4 Workflow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     LLM-as-a-Judge Evaluation Workflow                  │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Data Source    │     │  Data Filtering  │     │ Prompt Creation  │
│    (Weaviate)    │────▶│   & Validation   │────▶│  & Formatting    │
└──────────────────┘     └──────────────────┘     └──────────────────┘
        │                         │                         │
        │                         │                         │
        ▼                         ▼                         ▼
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  - MealPlan      │     │ Filters:         │     │ Components:      │
│  - MealLogEntry  │     │ - Date >= 01/05  │     │ - User Profile   │
│  - UserProfile   │     │ - No test data   │     │ - Meal Plan      │
│                  │     │ - Kcal > 50% tgt │     │ - Eval Criteria  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                                           │
                                                           ▼
                                          ┌──────────────────────────┐
                                          │    LLM Judge API Call    │
                                          │   (OpenRouter + Models)  │
                                          └──────────────────────────┘
                                                           │
                                                           ▼
                                          ┌──────────────────────────┐
                                          │    JSON Response Parse   │
                                          │   & Validation           │
                                          └──────────────────────────┘
                                                           │
                           ┌───────────────────────────────┼───────────────────────────────┐
                           ▼                               ▼                               ▼
               ┌──────────────────┐           ┌──────────────────┐           ┌──────────────────┐
               │   Score Metrics  │           │ Feedback/Suggest │           │ Results Storage  │
               │  - Overall: 78.5 │           │ - 3 Strengths    │           │ - JSON files     │
               │  - Nutrition: 72 │           │ - 3 Suggestions  │           │ - MD summaries   │
               │  - Variety: 85   │           │                  │           │                  │
               │  - Balance: 75   │           │                  │           │                  │
               │  - Feasibility:82│           │                  │           │                  │
               └──────────────────┘           └──────────────────┘           └──────────────────┘
```

---

## 5. Multi-Model Evaluation Results

The evaluation was conducted using four different LLM models as judges:

| Rank | Model | Overall Mean | Nutrition | Variety | Balance | Feasibility |
|------|-------|--------------|-----------|---------|---------|-------------|
| 1 | xiaomi/mimo-v2-flash:free | **80.23** | 74.23 | 81.00 | 82.83 | 82.87 |
| 2 | google/gemini-3-flash-preview | **78.80** | 73.87 | 79.30 | 78.03 | 84.00 |
| 3 | x-ai/grok-4.1-fast | **77.48** | 76.10 | 76.30 | 76.50 | 85.20 |
| 4 | openai/gpt-5-mini | **60.19** | 54.57 | 62.80 | 58.80 | 64.57 |

### Key Observations:

1. **Top 3 models agree**: xiaomi, gemini, and grok all score plans in the 77-80 range, suggesting consistent evaluation standards.

2. **GPT-5-mini is stricter**: Scores significantly lower across all criteria, potentially using different internal thresholds.

3. **Feasibility scores highest**: All models agree that the plans are highly feasible (Vietnamese dishes, familiar ingredients).

4. **Nutrition scores lowest**: Expected due to calorie/protein gaps between actual and target values.

5. **Excellent+Good rate**: Top 3 models rate ~93% of plans as Excellent (≥80) or Good (70-80).

---

## 6. References

### 6.1 Source Code Files

| Component | File Path |
|-----------|-----------|
| LLM Judge Implementation | `evaluation/metrics/llm_judge.py` |
| Elysia DecisionPrompt | `elysia/elysia/tree/prompt_templates.py` |
| Elysia QueryCreator | `elysia/elysia/tools/retrieval/prompt_templates.py` |
| MealAgent MealDraft | `MealAgent/tools/utils/llm_draft.py` |
| MealAgent MealParse | `MealAgent/tools/meal_logging/log_meal_e2e.py` |
| Evaluation Runner | `evaluation/scripts/run_single_method.py` |

### 6.2 Related Documentation

- `MealAgent/docs/DATA_PIPELINE.md` - Data pipeline architecture
- `MealAgent/docs/PLAN_DAY_WORKFLOW.md` - Day planning workflow
- `MealAgent/tools/TOOLS_DOCUMENTATION.md` - Tool I/O documentation
- `evaluation/README.md` - Evaluation setup and usage guide

### 6.3 Evaluation Results

- `evaluation/results/llm_judge_all_models_summary.md` - Multi-model comparison
- `evaluation/results/llm_judge_test__*.json` - Raw evaluation results per model
- `evaluation/results/llm_judge_summary__*.json` - Summary statistics per model

---

*End of Document*

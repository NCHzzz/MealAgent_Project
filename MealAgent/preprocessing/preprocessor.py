"""
MealAgent Preprocessor (Task 1.4.3)

This script uses Elysia's official Preprocessor API to generate
metadata summaries for collections and store them in `ELYSIA_METADATA__`.

Reference: https://weaviate.github.io/elysia/Reference/Preprocessor/
"""

from typing import List
import argparse
from elysia.preprocessing.collection import (
    preprocess,
    preprocessed_collection_exists,
    preprocessed_collection_exists_async,
    preprocess_async,
    edit_preprocessed_collection,
    delete_preprocessed_collection_async,
)
from elysia.util.client import ClientManager
from elysia.util.collection import async_get_collection_data_types
from elysia.util.async_util import asyncio_run


# All MealAgent collections that need preprocessing
# Default preprocessing knobs (script mode)
DEFAULT_MIN_SAMPLE_SIZE = 10
DEFAULT_MAX_SAMPLE_SIZE: int | None = None
DEFAULT_NUM_SAMPLE_TOKENS = 30_000
DEFAULT_FORCE = False

# Default MealAgent-targeted collections (excludes Recipe + FDC data sources)
DEFAULT_COLLECTIONS: list[str] = [
    "UserProfile",
    "MealPlan",
    "MealPlanItem",
    "MealLogEntry",
    "Pantry",
    "PantryItem",
    "ShoppingList",
    "ShoppingItem",
]

def _create_generic_mapping(collection_name: str, properties: dict) -> dict[str, str]:
    """
    Create intelligent generic mapping from collection fields to Elysia's generic return type.
    Maps collection-specific fields to: title, subtitle, content, url, id, author, timestamp, tags, category, subcategory
    
    Returns: dict mapping generic field -> collection field (empty string if no mapping)
    """
    from elysia.util import return_types as rt
    
    # Initialize with empty strings for all generic fields
    mapping = {field: "" for field in rt.generic.keys()}
    
    # Collection-specific mapping strategies
    if collection_name == "Recipe":
        mapping["title"] = "dish_name" if "dish_name" in properties else ""
        mapping["subtitle"] = "dish_type" if "dish_type" in properties else ""
        mapping["content"] = "ingredients_with_qty" if "ingredients_with_qty" in properties else ("ingredients" if "ingredients" in properties else "")
        mapping["url"] = "image_link" if "image_link" in properties else ""
        mapping["id"] = "food_id" if "food_id" in properties else ""
        mapping["tags"] = "allergens" if "allergens" in properties else ("diet_type" if "diet_type" in properties else "")
        mapping["category"] = "dish_type" if "dish_type" in properties else ""
        mapping["subcategory"] = "cooking_method_array" if "cooking_method_array" in properties else ""
        mapping["timestamp"] = ""  # Recipes don't have timestamps typically
        
    elif collection_name == "FdcFood":
        mapping["title"] = "description" if "description" in properties else ""
        mapping["subtitle"] = ""  # FdcFood doesn't have subtitle
        mapping["content"] = "description" if "description" in properties else ""
        mapping["id"] = "fdc_id" if "fdc_id" in properties else ""
        mapping["category"] = ""  # Could be derived from description but not in schema
        mapping["timestamp"] = ""
        
    elif collection_name == "UserProfile":
        # Primary card: show who the profile belongs to and their goal
        mapping["title"] = "display_name" if "display_name" in properties else ("user_id" if "user_id" in properties else "")
        mapping["subtitle"] = "goal" if "goal" in properties else ""
        mapping["content"] = ""  # Structured profile; no single free-text content field
        mapping["id"] = "user_id" if "user_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        # Tags reflect constraints & preferences for quick scanning
        mapping["tags"] = "preferences" if "preferences" in properties else ("allergens" if "allergens" in properties else "")
        # Category/subcategory align with MealAgent semantics: what they’re aiming for and how they eat
        mapping["category"] = "goal" if "goal" in properties else ""
        mapping["subcategory"] = "diet_type" if "diet_type" in properties else ""
        mapping["timestamp"] = "updated_at" if "updated_at" in properties else ("created_at" if "created_at" in properties else "")
        
    elif collection_name == "MealPlan":
        # Show plan type first (day/week) and keep ID for linking
        mapping["title"] = "plan_type" if "plan_type" in properties else ("plan_id" if "plan_id" in properties else "")
        mapping["subtitle"] = "start_date" if "start_date" in properties else ""
        mapping["id"] = "plan_id" if "plan_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        mapping["category"] = "plan_type" if "plan_type" in properties else ""
        mapping["timestamp"] = "created_at" if "created_at" in properties else ("start_date" if "start_date" in properties else "")
        
    elif collection_name == "MealPlanItem":
        # Emphasise meal type (breakfast/lunch/dinner/snack) and recipe linkage
        mapping["title"] = "meal_type" if "meal_type" in properties else ("recipe_id" if "recipe_id" in properties else "")
        mapping["subtitle"] = "recipe_id" if "recipe_id" in properties else ""
        mapping["content"] = "recipe_id" if "recipe_id" in properties else ""
        mapping["id"] = "plan_id" if "plan_id" in properties else ""
        mapping["category"] = "meal_type" if "meal_type" in properties else ""
        mapping["subcategory"] = "day_index" if "day_index" in properties else ""
        mapping["timestamp"] = ""
        
    elif collection_name == "MealLogEntry":
        mapping["title"] = "parsed_dish" if "parsed_dish" in properties else ("meal_description" if "meal_description" in properties else "")
        mapping["subtitle"] = "validation_status" if "validation_status" in properties else ""
        mapping["content"] = "meal_description" if "meal_description" in properties else ""
        mapping["id"] = "log_id" if "log_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        mapping["tags"] = "ingredients" if "ingredients" in properties else ""
        mapping["category"] = "parsing_method" if "parsing_method" in properties else ""
        mapping["timestamp"] = "logged_at" if "logged_at" in properties else ""
        
    elif collection_name == "Pantry":
        # One pantry per user – treat as a profile-style card
        mapping["title"] = "user_id" if "user_id" in properties else ""
        mapping["id"] = "user_id" if "user_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        mapping["timestamp"] = "updated_at" if "updated_at" in properties else ""
        
    elif collection_name == "PantryItem":
        # Show ingredient name + unit, and use tags for quick filtering
        mapping["title"] = "ingredient_name" if "ingredient_name" in properties else ""
        mapping["subtitle"] = "unit" if "unit" in properties else ""
        mapping["content"] = "ingredient_name" if "ingredient_name" in properties else ""
        mapping["id"] = "fdc_id" if "fdc_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        mapping["tags"] = "ingredient_name" if "ingredient_name" in properties else ""
        mapping["category"] = ""  # Could be derived from ingredient but not in schema
        mapping["timestamp"] = "expiry_date" if "expiry_date" in properties else ""
        
    elif collection_name == "ShoppingList":
        # List card: show list id and link back to the originating plan
        mapping["title"] = "list_id" if "list_id" in properties else ""
        mapping["subtitle"] = "plan_id" if "plan_id" in properties else ""
        mapping["id"] = "list_id" if "list_id" in properties else ""
        mapping["author"] = "user_id" if "user_id" in properties else ""
        mapping["tags"] = "plan_id" if "plan_id" in properties else ""
        mapping["timestamp"] = "created_at" if "created_at" in properties else ""
        
    elif collection_name == "ShoppingItem":
        # Item row within a list: emphasise ingredient and category
        mapping["title"] = "ingredient_name" if "ingredient_name" in properties else ""
        mapping["subtitle"] = "category" if "category" in properties else ""
        mapping["content"] = "ingredient_name" if "ingredient_name" in properties else ""
        mapping["id"] = "list_id" if "list_id" in properties else ""
        mapping["category"] = "category" if "category" in properties else ""
        mapping["subcategory"] = "unit" if "unit" in properties else ""
        mapping["tags"] = "category" if "category" in properties else ""
        mapping["timestamp"] = ""
        
    elif collection_name == "FdcNutrient":
        mapping["title"] = "nutrient_name" if "nutrient_name" in properties else ""
        mapping["subtitle"] = "unit" if "unit" in properties else ""
        mapping["id"] = "fdc_id" if "fdc_id" in properties else ""
        mapping["category"] = "nutrient_name" if "nutrient_name" in properties else ""
        mapping["timestamp"] = ""
        
    elif collection_name == "FdcPortion":
        mapping["title"] = "measure_unit" if "measure_unit" in properties else ""
        mapping["subtitle"] = "amount" if "amount" in properties else ""
        mapping["id"] = "fdc_id" if "fdc_id" in properties else ""
        mapping["category"] = "measure_unit" if "measure_unit" in properties else ""
        mapping["timestamp"] = ""
    
    # Verify all mapped fields actually exist in properties
    # If a mapped field doesn't exist, set to empty string
    for generic_field, collection_field in list(mapping.items()):
        if collection_field and collection_field not in properties:
            mapping[generic_field] = ""
    
    return mapping


def _get_field_descriptions(collection_name: str, properties: dict) -> dict[str, str]:
    """
    Get detailed field descriptions for a collection based on its schema.
    Returns: dict mapping field_name -> description
    """
    # Field descriptions by collection
    field_desc_map = {
        "UserProfile": {
            "user_id": "Unique identifier for the user. Used for data isolation and filtering.",
            "email": "User's email address for authentication and communication.",
            "password_hash": "Hashed password for user authentication (not displayed).",
            "display_name": "User's display name or nickname.",
            "age": "User's age in years. Used for TDEE calculation via Harris-Benedict formula.",
            "gender": "User's gender: 'male', 'female', or 'other'. Used for TDEE calculation.",
            "weight_kg": "User's weight in kilograms. Used for TDEE and macro calculations.",
            "height_cm": "User's height in centimeters. Used for TDEE calculation.",
            "activity_level": "Activity level: 'sedentary', 'light', 'moderate', 'very_active', or 'extra_active'. Used for TDEE calculation.",
            "goal": "Fitness goal: 'weight_loss', 'weight_gain', 'muscle_gain', or 'maintenance'. Affects macro targets.",
            "timeline_months": "Goal timeline in months (e.g., 3 for aggressive, 6 for sustainable). Used to pace macro adjustments.",
            "diet_type": "Dietary preference (e.g., 'vegetarian', 'vegan', 'keto', 'paleo'). Used for recipe filtering.",
            "allergens": "Array of allergens to avoid (e.g., ['peanuts', 'dairy', 'gluten']). Used for recipe filtering.",
            "preferences": "Array of liked cuisines or ingredients. Used for recipe ranking.",
            "max_cooking_time_min": "Maximum cooking time in minutes. Used as a constraint for recipe filtering.",
            "available_equipment": "Array of available cooking equipment (e.g., ['oven', 'stovetop']). Used for recipe filtering.",
            "tdee_kcal": "Total Daily Energy Expenditure in calories. Calculated from age, gender, weight, height, and activity level.",
            "protein_g": "Daily protein target in grams. Calculated based on TDEE and goal.",
            "fat_g": "Daily fat target in grams. Calculated based on TDEE and goal.",
            "carb_g": "Daily carbohydrate target in grams. Calculated based on TDEE and goal.",
            "micronutrient_targets": "Object containing micronutrient targets (vitamins and minerals) in various units.",
            "created_at": "Timestamp when the profile was created.",
            "updated_at": "Timestamp when the profile was last updated.",
        },
        "MealPlan": {
            "plan_id": "Unique identifier for the meal plan.",
            "user_id": "User who owns this meal plan. Used for filtering and data isolation.",
            "plan_type": "Type of plan: 'day' for daily plans or 'week' for weekly plans.",
            "start_date": "Start date of the meal plan.",
            "created_at": "Timestamp when the meal plan was created.",
        },
        "MealPlanItem": {
            "plan_id": "ID of the meal plan this item belongs to. Links to MealPlan collection.",
            "day_index": "Day index (0-6) for weekly plans. 0 = first day, 6 = last day. Not used for daily plans.",
            "meal_type": "Type of meal: 'breakfast', 'lunch', 'dinner', or 'snack'.",
            "recipe_id": "ID of the recipe for this meal. Links to Recipe collection.",
            "servings": "Number of servings (portion multiplier) for this meal.",
            "actual_macros": "Calculated macros for this meal portion stored as JSON string: {kcal, protein_g, fat_g, carb_g}.",
        },
        "MealLogEntry": {
            "log_id": "Unique identifier for the meal log entry.",
            "user_id": "User who logged this meal. Used for filtering and data isolation.",
            "logged_at": "Timestamp when the meal was logged.",
            "meal_description": "Original natural language description from user (e.g., 'I ate chicken salad').",
            "parsed_dish": "Dish name extracted by LLM from meal_description.",
            "ingredients": "JSON string array of parsed ingredients: [{name, amount, unit, fdc_id?}].",
            "portion_size": "Portion multiplier for the logged meal.",
            "calculated_macros": "JSON string of calculated macros: {kcal, protein_g, fat_g, carb_g}.",
            "calculated_micros": "JSON string of calculated micronutrients if available.",
            "validation_status": "Status: 'complete' (all ingredients resolved), 'partial' (some resolved), or 'failed'.",
            "parsing_method": "Method used: 'llm' (LLM parsing) or 'manual_fallback' (manual input).",
        },
        "Pantry": {
            "user_id": "User who owns this pantry. Used for filtering and data isolation.",
            "updated_at": "Timestamp when the pantry was last updated.",
        },
        "PantryItem": {
            "user_id": "User who owns this pantry item. Used for filtering and data isolation.",
            "ingredient_name": "Name of the ingredient (e.g., 'chicken breast', 'olive oil').",
            "quantity": "Quantity of the ingredient.",
            "unit": "Unit of measurement (e.g., 'g', 'kg', 'cup', 'piece').",
            "fdc_id": "Optional link to FdcFood collection for nutritional information.",
            "expiry_date": "Optional expiry date for perishable items.",
        },
        "ShoppingList": {
            "list_id": "Unique identifier for the shopping list.",
            "user_id": "User who owns this shopping list. Used for filtering and data isolation.",
            "plan_id": "ID of the meal plan this shopping list was generated from. Links to MealPlan collection.",
            "created_at": "Timestamp when the shopping list was created.",
        },
        "ShoppingItem": {
            "list_id": "ID of the shopping list this item belongs to. Links to ShoppingList collection.",
            "ingredient_name": "Name of the ingredient to purchase.",
            "quantity": "Quantity needed.",
            "unit": "Unit of measurement (e.g., 'g', 'kg', 'cup').",
            "category": "Category for grouping (e.g., 'produce', 'dairy', 'meat', 'pantry').",
            "purchased": "Boolean flag indicating if the item has been purchased.",
        },
        "Recipe": {
            "food_id": "Unique identifier for the recipe (from CSV source).",
            "dish_name": "Name of the dish (Vietnamese). Used for vectorization and search.",
            "dish_type": "Type of dish (e.g., 'main course', 'appetizer', 'dessert').",
            "serving_size": "Number of servings this recipe makes.",
            "cooking_time": "Cooking time in minutes. Used for filtering by max_cooking_time_min constraint.",
            "ingredients_with_qty": "Array of ingredients with quantities (Vietnamese). Used for vectorization.",
            "ingredients": "Array of ingredient names without quantities (Vietnamese). Used for vectorization.",
            "cooking_method_array": "Array of cooking methods (e.g., ['fry', 'steam', 'bake']). Used for vectorization.",
            "image_link": "URL to recipe image.",
            "diet_type": "Array of diet types this recipe supports (e.g., ['vegetarian', 'vegan', 'keto']). Used for filtering.",
            "allergens": "Array of allergens present (e.g., ['peanuts', 'dairy', 'gluten']). Used for filtering.",
            "devices": "Array of required cooking equipment (e.g., ['oven', 'stovetop']). Used for filtering.",
            "macros_per_serving": "Cached object with macros per serving: {kcal, protein_g, fat_g, carb_g}. Computed on-demand by calculate_recipe_macros_tool.",
            "ingredient_fdc_map": "Cached array mapping Vietnamese ingredients to FDC foods: [{ingredient_vn, ingredient_en, fdc_id, quantity_g, confidence}]. Computed on-demand.",
        },
        "FdcFood": {
            "fdc_id": "Unique FoodData Central identifier. Primary key linking to FdcNutrient and FdcPortion.",
            "description": "Food description (English). Used for vectorization and semantic search.",
            "energy_kcal_100g": "Energy content per 100g in kilocalories.",
            "protein_g_100g": "Protein content per 100g in grams.",
            "fat_g_100g": "Total fat content per 100g in grams.",
            "carbohydrate_g_100g": "Total carbohydrate content per 100g in grams.",
            "sugars_g_100g": "Sugars content per 100g in grams.",
            "fiber_g_100g": "Dietary fiber content per 100g in grams.",
            "sodium_mg_100g": "Sodium content per 100g in milligrams.",
            "sat_fat_g_100g": "Saturated fat content per 100g in grams.",
            "calcium_mg_100g": "Calcium content per 100g in milligrams.",
            "iron_mg_100g": "Iron content per 100g in milligrams.",
            "potassium_mg_100g": "Potassium content per 100g in milligrams.",
            "magnesium_mg_100g": "Magnesium content per 100g in milligrams.",
            "zinc_mg_100g": "Zinc content per 100g in milligrams.",
            "vitamin_a_rae_ug_100g": "Vitamin A (RAE) content per 100g in micrograms.",
            "vitamin_b6_mg_100g": "Vitamin B6 content per 100g in milligrams.",
            "vitamin_b12_ug_100g": "Vitamin B12 content per 100g in micrograms.",
            "thiamin_b1_mg_100g": "Thiamin (B1) content per 100g in milligrams.",
            "riboflavin_b2_mg_100g": "Riboflavin (B2) content per 100g in milligrams.",
            "niacin_b3_mg_100g": "Niacin (B3) content per 100g in milligrams.",
            "vitamin_c_mg_100g": "Vitamin C content per 100g in milligrams.",
            "vitamin_d_ug_100g": "Vitamin D content per 100g in micrograms.",
            "vitamin_e_mg_100g": "Vitamin E content per 100g in milligrams.",
        },
        "FdcNutrient": {
            "fdc_id": "FoodData Central identifier linking to FdcFood. Foreign key.",
            "nutrient_id": "FDC nutrient identifier (e.g., 1008 = Energy, 1003 = Protein).",
            "nutrient_name": "Name of the nutrient (e.g., 'Protein', 'Vitamin C', 'Iron').",
            "amount_100g": "Amount of nutrient per 100g of food.",
            "unit": "Unit of measurement for the nutrient (e.g., 'g', 'mg', 'mcg', 'IU').",
        },
        "FdcPortion": {
            "fdc_id": "FoodData Central identifier linking to FdcFood. Foreign key.",
            "amount": "Amount of the portion (e.g., 1.0 for '1 cup').",
            "measure_unit": "Unit of measurement (e.g., 'cup', 'oz', 'tbsp', 'piece', 'waffle, square').",
            "gram_weight": "Weight of this portion in grams. Used for converting household measures to grams.",
        },
    }
    
    return field_desc_map.get(collection_name, {})


def _get_collection_description(collection_name: str, properties: dict) -> tuple[str, list[str]]:
    """
    Get detailed description and prompts for a collection based on its purpose.
    Returns: (summary, prompts_list)
    """
    # Collection-specific descriptions based on design documentation
    descriptions = {
        "UserProfile": (
            "**UserProfile** collection stores user demographic information, dietary constraints, "
            "and calculated nutritional targets (TDEE, macros, micronutrients). This is the single "
            "source of truth for user preferences and nutritional goals. Each user has one profile "
            "that is updated as they log meals and create plans. The collection includes fields "
            "for age, gender, weight, height, activity level, diet type, allergens, preferences, "
            "and calculated targets like TDEE (Total Daily Energy Expenditure) and macro/micro targets.",
            [
                "Show me my user profile",
                "What are my nutritional targets?",
                "Update my dietary preferences",
                "What allergens do I have?",
                "Show my calculated TDEE and macros",
            ]
        ),
        "MealPlan": (
            "**MealPlan** collection stores meal planning metadata. Each plan represents a daily "
            "or weekly meal plan created for a user. Plans are linked to users via `user_id` and "
            "contain metadata like plan type (day/week), start date, and creation timestamp. "
            "Individual meal items are stored in the related `MealPlanItem` collection.",
            [
                "Show me my meal plans",
                "What meal plans do I have?",
                "Create a new meal plan",
                "Show plans for this week",
            ]
        ),
        "MealPlanItem": (
            "**MealPlanItem** collection stores individual meal entries within a meal plan. "
            "Each item represents one meal (breakfast, lunch, dinner, snack) on a specific day "
            "of a plan. Items reference recipes via `recipe_id` and include serving sizes and "
            "calculated macros for that portion. For weekly plans, `day_index` (0-6) indicates "
            "which day of the week the meal belongs to.",
            [
                "What meals are in my plan?",
                "Show me breakfast items in my plan",
                "What recipes are scheduled for today?",
                "Show meal macros for my plan",
            ]
        ),
        "MealLogEntry": (
            "**MealLogEntry** collection stores logged meal consumption records. Users log meals "
            "in natural language (e.g., 'I ate chicken salad'), which is parsed by LLM to extract "
            "ingredients and portions. Each entry includes parsed dish name, ingredients (as JSON), "
            "calculated macros/micros, portion size, validation status, and timestamp. This collection "
            "serves as an audit trail for nutrition tracking and helps update remaining nutritional targets.",
            [
                "Show my meal history",
                "What meals did I eat today?",
                "Log a meal I just ate",
                "Show my nutrition consumption for this week",
                "What are my logged meals?",
            ]
        ),
        "Pantry": (
            "**Pantry** collection stores user pantry metadata. Each user has one pantry record "
            "that tracks when it was last updated. Individual pantry items are stored in the "
            "related `PantryItem` collection. The pantry is used by planning tools to prioritize "
            "recipes that use ingredients already available.",
            [
                "Show my pantry",
                "What's in my pantry?",
                "Update my pantry",
            ]
        ),
        "PantryItem": (
            "**PantryItem** collection stores individual ingredients in a user's pantry. Each item "
            "includes ingredient name, quantity, unit, optional FDC food ID link, and optional expiry date. "
            "Planning tools consult pantry items to suggest recipes using available ingredients. "
            "The `pantry_diff_tool` compares meal plan ingredient demands against pantry items to "
            "generate shopping lists.",
            [
                "What ingredients do I have?",
                "Show pantry items expiring soon",
                "Add ingredient to pantry",
                "Remove ingredient from pantry",
            ]
        ),
        "ShoppingList": (
            "**ShoppingList** collection stores shopping list metadata. Each list is generated "
            "from a meal plan and linked via `plan_id`. Lists are created by `pantry_diff_tool` "
            "which calculates ingredient demands from meal plans and subtracts available pantry items. "
            "Individual shopping items are stored in the related `ShoppingItem` collection.",
            [
                "Show my shopping lists",
                "Generate shopping list from meal plan",
                "What shopping lists do I have?",
            ]
        ),
        "ShoppingItem": (
            "**ShoppingItem** collection stores individual items on a shopping list. Each item "
            "includes ingredient name, quantity, unit, category (for grouping like 'produce', 'dairy'), "
            "and a `purchased` flag to track completion. Items are organized by category for easy "
            "shopping and can be marked as purchased as the user shops.",
            [
                "What items are on my shopping list?",
                "Show shopping list items by category",
                "Mark shopping item as purchased",
                "What do I need to buy?",
            ]
        ),
        "Recipe": (
            "**Recipe** collection stores Vietnamese recipe data with vectorization for semantic search. "
            "Recipes include dish names, ingredients, cooking methods, and cached nutritional information. "
            "The collection supports filtering by diet type, allergens, cooking time, and required equipment. "
            "Macros per serving are computed on-demand via `calculate_recipe_macros_tool` which translates "
            "Vietnamese ingredients to English and looks them up in FdcFood. Recipes are used by planning "
            "tools, search tools, and cooking mode.",
            [
                "Find vegetarian pasta recipes",
                "Show me recipes with less than 30 minutes cooking time",
                "Search for recipes without dairy",
                "What recipes use ingredients I have?",
                "Show me keto-friendly recipes",
            ]
        ),
        "FdcFood": (
            "**FdcFood** collection stores FoodData Central food items with comprehensive nutritional data "
            "per 100g. This is the canonical source for macro and micronutrient values. Foods are vectorized "
            "by description for semantic search. The collection links to FdcNutrient (fine-grained nutrients) "
            "and FdcPortion (portion conversions). Used by `calculate_recipe_macros_tool` to compute recipe "
            "nutrition and by meal logging tools to calculate consumed nutrients.",
            [
                "Find foods high in protein",
                "What foods are rich in vitamin C?",
                "Search for low-carb foods",
                "Show me foods with high iron content",
                "Find foods suitable for keto diet",
            ]
        ),
        "FdcNutrient": (
            "**FdcNutrient** collection stores fine-grained nutrient entries for FDC foods. Each row represents "
            "one nutrient for one food, keyed by (fdc_id, nutrient_id). Used when micronutrient-level accuracy "
            "is required (e.g., vitamin C deficit analysis). Tools deserialize rows into structured micronutrient "
            "objects. Links to FdcFood via fdc_id.",
            [
                "What nutrients are in this food?",
                "Show vitamin C content for foods",
                "Find foods with specific nutrient levels",
            ]
        ),
        "FdcPortion": (
            "**FdcPortion** collection stores portion conversion data for FDC foods. Converts household measures "
            "(cups, ounces, tablespoons) to gram weights. Essential for accurate nutrition calculations when users "
            "specify portions in household units. Used by `calculate_recipe_macros_tool` and meal logging tools "
            "to normalize ingredient quantities before combining with FdcFood nutrient densities. Links to FdcFood via fdc_id.",
            [
                "How many grams is 1 cup of spinach?",
                "Convert household measures to grams",
                "What portion sizes are available for this food?",
            ]
        ),
    }
    
    # Get collection-specific description or create generic one
    if collection_name in descriptions:
        summary, prompts = descriptions[collection_name]
        # Add field information to summary
        field_names = ", ".join(list(properties.keys())[:5])
        if len(properties) > 5:
            field_names += f", and {len(properties) - 5} more"
        summary += f" The collection contains {len(properties)} fields: {field_names}."
        summary += " The collection is currently empty but will store data as users interact with the system."
        return summary, prompts
    else:
        # Generic description for collections not in the list
        field_names = ", ".join(list(properties.keys())[:5])
        if len(properties) > 5:
            field_names += f", and {len(properties) - 5} more"
        summary = (
            f"**{collection_name}** collection. "
            f"This collection contains {len(properties)} fields: {field_names}. "
            f"The collection is currently empty but will store data as users interact with the system."
        )
        prompts = [
            f"What {collection_name.lower()} data exists?",
            f"Show me all {collection_name.lower()} records",
            f"Create a new {collection_name.lower()} entry",
        ]
        return summary, prompts


async def _preprocess_collection_safe(
    collection_name: str,
    client_manager: ClientManager,
    min_sample_size: int = 10,
    max_sample_size: int | None = None,
    num_sample_tokens: int = 30000,
    force: bool = False,
) -> None:
    """
    Safely preprocess a collection, handling empty collections gracefully.
    
    For empty collections, creates minimal metadata based on schema only.
    For collections with data, uses the standard Elysia preprocessor.
    """
    # Check if collection exists
    async with client_manager.connect_to_async_client() as client:
        if not await client.collections.exists(collection_name):
            raise Exception(f"Collection {collection_name} does not exist!")
        
        # Check if already preprocessed
        if (
            await preprocessed_collection_exists_async(collection_name, client_manager)
            and not force
        ):
            print(f"✓ {collection_name} already preprocessed, skipping...")
            return
        
        # Check collection size
        collection = client.collections.get(collection_name)
        agg = await collection.aggregate.over_all(total_count=True)
        len_collection: int = agg.total_count  # type: ignore
        
        if len_collection == 0:
            # Handle empty collection: create minimal metadata from schema
            print(f"⚠ {collection_name} is empty, creating minimal metadata from schema...")
            await _create_minimal_metadata(collection_name, client_manager, collection)
        else:
            # Use standard preprocessor for collections with data
            print(f"📊 Preprocessing {collection_name} ({len_collection} objects)...")
            async for update in preprocess_async(
                collection_name=collection_name,
        client_manager=client_manager,
        min_sample_size=min_sample_size,
        max_sample_size=max_sample_size,
        num_sample_tokens=num_sample_tokens,
        force=force,
            ):
                # Stream progress updates (optional - can be removed for silent mode)
                if update.get("error"):
                    raise Exception(f"Error preprocessing {collection_name}: {update['error']}")


async def _create_minimal_metadata(
    collection_name: str,
    client_manager: ClientManager,
    collection,
) -> None:
    """
    Create minimal metadata for an empty collection based on schema only.
    This allows Elysia to work with collections that don't have data yet.
    """
    from elysia.util.collection import async_get_collection_data_types
    from elysia.util.parsing import format_dict_to_serialisable
    from weaviate.classes.config import Configure, Property, DataType, Tokenization
    
    # Get collection properties from schema
    async with client_manager.connect_to_async_client() as client:
        properties = await async_get_collection_data_types(client, collection_name)
        
        # Get vectorizer info
        schema_info = await collection.config.get()
        named_vectors = None
        vectoriser = None
        
        if schema_info.vector_config:
            named_vectors = [
                {
                    "name": vector,
                    "vectorizer": schema_info.vector_config[vector].vectorizer.vectorizer.name,
                    "model": (
                        schema_info.vector_config[vector].vectorizer.model.get("model")
                        if "model" in schema_info.vector_config[vector].vectorizer.model
                        else None
                    ),
                    "source_properties": schema_info.vector_config[vector].vectorizer.source_properties,
                    "enabled": True,
                    "description": "",
                }
                for vector in schema_info.vector_config
            ]
        
        if schema_info.vectorizer_config:
            vectoriser = {
                "vectorizer": schema_info.vectorizer_config.vectorizer.name,
                "model": (
                    schema_info.vectorizer_config.model.get("model")
                    if "model" in schema_info.vectorizer_config.model
                    else None
                ),
            }
        
        # Get collection-specific descriptions and field descriptions
        summary, prompts = _get_collection_description(collection_name, properties)
        
        # Field-specific descriptions based on collection type
        field_descriptions = _get_field_descriptions(collection_name, properties)
        
        # Create minimal field statistics (no data, so use defaults)
        # Structure must match Elysia's _evaluate_field_statistics output exactly
        fields = []
        for prop_name, prop_type in properties.items():
            # Get field description (use empty string if not found to match Elysia behavior)
            # But we provide detailed descriptions when available for better metadata
            field_desc = field_descriptions.get(prop_name, "")
            
            # Field structure must match Elysia's _evaluate_field_statistics exactly:
            # name, type, description, range, mean, date_range, date_median, groups
            field_info = {
                "name": prop_name,
                "type": prop_type if prop_type != "number" else "float",
                "description": field_desc,  # Can be empty string or detailed description
                "range": None,
                "mean": None,
                "date_range": None,
                "date_median": None,
                "groups": None,
            }
            fields.append(field_info)
        
        # Create intelligent generic mapping based on collection structure
        generic_mapping = _create_generic_mapping(collection_name, properties)
        
        # Create minimal metadata object
        metadata = {
            "name": collection_name,
            "length": 0,
            "summary": summary,
            "index_properties": {
                "isNullIndexed": schema_info.inverted_index_config.index_null_state,
                "isLengthIndexed": schema_info.inverted_index_config.index_property_length,
                "isTimestampIndexed": schema_info.inverted_index_config.index_timestamps,
            },
            "named_vectors": named_vectors,
            "vectorizer": vectoriser,
            "fields": fields,
            "mappings": {
                "generic": generic_mapping,
                "table": {field: field for field in properties.keys()},
            },
            "prompts": prompts,
        }
        
        format_dict_to_serialisable(metadata)
        
        # Delete existing metadata if it exists
        if await preprocessed_collection_exists_async(collection_name, client_manager):
            await delete_preprocessed_collection_async(collection_name, client_manager)
        
        # Save to ELYSIA_METADATA__
        metadata_name = "ELYSIA_METADATA__"
        if await client.collections.exists(metadata_name):
            metadata_collection = client.collections.get(metadata_name)
        else:
            metadata_collection = await client.collections.create(
                metadata_name,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="name", data_type=DataType.TEXT, tokenization=Tokenization.FIELD),
                    Property(name="length", data_type=DataType.NUMBER),
                    Property(name="summary", data_type=DataType.TEXT),
                    Property(
                        name="index_properties",
                        data_type=DataType.OBJECT,
                        nested_properties=[
                            Property(name="isNullIndexed", data_type=DataType.BOOL),
                            Property(name="isLengthIndexed", data_type=DataType.BOOL),
                            Property(name="isTimestampIndexed", data_type=DataType.BOOL),
                        ],
                    ),
                    Property(
                        name="named_vectors",
                        data_type=DataType.OBJECT_ARRAY,
                        nested_properties=[
                            Property(name="name", data_type=DataType.TEXT),
                            Property(name="vectorizer", data_type=DataType.TEXT),
                            Property(name="model", data_type=DataType.TEXT),
                            Property(name="source_properties", data_type=DataType.TEXT_ARRAY),
                            Property(name="enabled", data_type=DataType.BOOL),
                            Property(name="description", data_type=DataType.TEXT),
                        ],
                    ),
                    Property(
                        name="vectorizer",
                        data_type=DataType.OBJECT,
                        nested_properties=[
                            Property(name="vectorizer", data_type=DataType.TEXT),
                            Property(name="model", data_type=DataType.TEXT),
                        ],
                    ),
                    Property(
                        name="fields",
                        data_type=DataType.OBJECT_ARRAY,
                        nested_properties=[
                            Property(name="name", data_type=DataType.TEXT),
                            Property(name="type", data_type=DataType.TEXT),
                            Property(name="description", data_type=DataType.TEXT),
                            Property(name="range", data_type=DataType.NUMBER_ARRAY),
                            Property(name="date_range", data_type=DataType.DATE_ARRAY),
                            Property(
                                name="groups",
                                data_type=DataType.OBJECT_ARRAY,
                                nested_properties=[
                                    Property(name="value", data_type=DataType.TEXT),
                                    Property(name="count", data_type=DataType.INT),
                                ],
                            ),
                            Property(name="date_median", data_type=DataType.DATE),
                            Property(name="mean", data_type=DataType.NUMBER),
                        ],
                    ),
                ],
                inverted_index_config=Configure.inverted_index(index_null_state=True),
            )
        
        await metadata_collection.data.insert(metadata)
        print(f"✓ Created minimal metadata for {collection_name}")




def _parse_cli_args() -> argparse.Namespace:
    """Parse CLI arguments for the standalone script."""
    parser = argparse.ArgumentParser(
        description="Preprocess MealAgent collections (metadata generation)."
    )
    parser.add_argument(
        "--min-sample",
        type=int,
        default=DEFAULT_MIN_SAMPLE_SIZE,
        help="Minimum number of objects sampled per collection.",
    )
    parser.add_argument(
        "--max-sample",
        type=int,
        default=DEFAULT_MAX_SAMPLE_SIZE,
        help="Maximum number of objects sampled per collection (omit for dynamic).",
    )
    parser.add_argument(
        "--num-tokens",
        type=int,
        default=DEFAULT_NUM_SAMPLE_TOKENS,
        help="Approximate token budget per collection summary.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=DEFAULT_FORCE,
        help="Re-run even if metadata already exists.",
    )
    parser.add_argument(
        "--collections",
        nargs="*",
        default=None,
        help="Collections to preprocess; default targets the MealAgent collections (excluding Recipe/FDC).",
    )
    return parser.parse_args()


def run() -> None:
    """
    Run preprocessing for all MealAgent collections **except** the core FDC/Recipe
    data sources (FdcFood, FdcNutrient, FdcPortion, Recipe).
    
    This is tailored to the MealAgent system:
    - We assume the four base data collections are either already preprocessed
      via the official Elysia preprocessor or are managed separately.
    - Here we focus on user/profile/planning/logging/pantry/shopping collections
      that power the MealAgent workflows.
    """
    args = _parse_cli_args()
    collections: list[str] = args.collections if args.collections else list(DEFAULT_COLLECTIONS)
    if len(collections) == 0:
        print("⚠ No collections specified; nothing to preprocess.")
        return
    client_manager = ClientManager()
    
    min_sample_size = args.min_sample
    max_sample_size = args.max_sample
    num_sample_tokens = args.num_tokens
    force = args.force
    
    print(f"🚀 Starting preprocessing for {len(collections)} collections...")
    print(f"Collections: {', '.join(collections)}\n")
    
    async def _run_async():
        try:
            for collection_name in collections:
                try:
                    await _preprocess_collection_safe(
                        collection_name=collection_name,
                        client_manager=client_manager,
                        min_sample_size=min_sample_size,
                        max_sample_size=max_sample_size,
                        num_sample_tokens=num_sample_tokens,
                        force=force,
                    )
                except Exception as e:
                    print(f"❌ Error preprocessing {collection_name}: {e}")
                    raise
            print(f"\n✅ Preprocessing complete for all collections!")
        finally:
            await client_manager.close_clients()
    
    asyncio_run(_run_async())


if __name__ == "__main__":
        run()


# (No standalone warm-ups; the official preprocessor samples objects and touches indexes.)


    



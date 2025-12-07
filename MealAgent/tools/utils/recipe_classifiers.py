"""
Recipe classification functions for meal planning.
Centralized to avoid duplication across tools.
"""

from typing import Dict, Any


def _is_vietnamese_breakfast(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a Vietnamese breakfast dish."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    breakfast_keywords = [
        "phở", "pho", "bun", "bún", "bun bo", "bún bò", "bun rieu", "bún riêu", "bun cha", "bún chả",
        "hu tieu", "hủ tiếu", "banh mi", "bánh mì", "banh cuon", "bánh cuốn",
        "banh canh", "bánh canh", "banh bao", "bánh bao",
        "xoi", "xôi", "chao", "cháo", "sandwich", "bánh ngọt", "banh ngot", "croissant", "brioche",
        "cơm tấm", "com tam", "xoi man", "xôi mặn", "xoi ngo", "xôi ngô"
    ]
    
    if any(keyword in dish_name for keyword in breakfast_keywords):
        return True
    
    if any(keyword in dish_type for keyword in breakfast_keywords):
        return True
    
    meal_type = str(recipe.get("meal_type", "")).lower()
    if "breakfast" in meal_type or "sáng" in meal_type:
        return True
    
    return False


def _is_rice_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a rice dish (cơm) - plain rice, not main dishes."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    rice_keywords = ["cơm", "com", "rice"]
    has_rice = any(keyword in dish_name or keyword in dish_type for keyword in rice_keywords)
    
    if not has_rice:
        return False
    
    # Exclude main dishes that don't have rice in name
    main_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
        "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
        "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien"
    ]
    has_main_keywords = any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)
    
    if has_main_keywords and not any(kw in dish_name for kw in rice_keywords):
        return False
    
    # Exclude breakfast dishes
    breakfast_keywords = ["bánh mì", "banh mi", "bánh cuốn", "banh cuon", "xôi", "xoi", "cháo", "chao", "phở", "pho"]
    if any(kw in dish_name or kw in dish_type for kw in breakfast_keywords):
        return False
    
    # Exclude cakes/pancakes
    cake_keywords = ["pancake", "bánh bông lan", "banh bong lan", "bánh ngọt", "banh ngot", "flan", "cake"]
    if any(kw in dish_name or kw in dish_type for kw in cake_keywords):
        return False
    
    # Exclude bean dishes
    if "đậu" in dish_name or "dau" in dish_name or "bean" in dish_name:
        return False
    
    return True


def _is_noodle_soup(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a noodle/soup dish (phở, bún, mì, canh)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Exclude cakes/pancakes
    cake_keywords = ["pancake", "bánh bông lan", "banh bong lan", "bánh ngọt", "banh ngot", "flan", "cake"]
    if any(kw in dish_name or kw in dish_type for kw in cake_keywords):
        return False
    
    noodle_keywords = [
        "phở", "pho", "bún", "bun", "bún bò", "bun bo", "bún riêu", "bun rieu",
        "bún chả", "bun cha", "hủ tiếu", "hu tieu", "mì", "mi ", "miến", "mien",
        "canh", "soup", "cháo", "chao"
    ]
    return any(kw in dish_name or kw in dish_type for kw in noodle_keywords)


def _is_soup(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a soup dish (canh) - Vietnamese soup typically served with rice."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    soup_keywords = ["canh", "soup"]
    exclude_keywords = ["phở", "pho", "bún", "bun", "mì", "mi ", "miến", "mien", "hủ tiếu", "hu tieu"]
    
    has_soup = any(kw in dish_name or kw in dish_type for kw in soup_keywords)
    has_noodle = any(kw in dish_name or kw in dish_type for kw in exclude_keywords)
    
    return has_soup and not has_noodle


def _is_main_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a main dish (món mặn)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Exclude breakfast
    breakfast_keywords = ["bánh mì", "banh mi", "bánh cuốn", "banh cuon", "xôi", "xoi", "cháo", "chao", "phở", "pho"]
    if any(kw in dish_name or kw in dish_type for kw in breakfast_keywords):
        return False
    
    # Exclude plain rice dishes
    rice_keywords = ["cơm", "com", "rice"]
    has_rice = any(keyword in dish_name or keyword in dish_type for keyword in rice_keywords)
    if has_rice:
        main_keywords = [
            "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
            "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
            "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien",
            "ba rọi", "ba roi", "pork belly", "sườn", "suon", "rib",
            "xúc xích", "xuc xich", "sausage", "giò", "gio", "bì", "bi",
            "đậu", "dau", "bean"
        ]
        has_main = any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)
        if not has_main:
            return False
    
    # Check for main dish keywords
    main_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
        "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
        "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien",
        "ba rọi", "ba roi", "pork belly", "sườn", "suon", "rib",
        "xúc xích", "xuc xich", "sausage", "giò", "gio", "bì", "bi",
        "lươn", "luon", "eel", "ếch", "ech", "frog", "ngâm", "ngam", "pickled"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)


def _is_vegetable_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a vegetable dish (rau) - pure vegetable, no protein."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Exclude combined dishes and main dishes
    if _is_combined_dish(recipe) or _is_main_dish(recipe):
        return False
    
    # Exclude breakfast items
    breakfast_keywords = [
        "bánh mì", "banh mi", "bánh cuốn", "banh cuon", "bánh bao", "banh bao", 
        "bánh canh", "banh canh", "bánh ngọt", "banh ngot", "bánh bông lan", "banh bong lan",
        "pancake", "flan", "cake", "bánh", "banh"
    ]
    if any(kw in dish_name or kw in dish_type for kw in breakfast_keywords):
        return False
    
    # Exclude dishes with protein keywords
    protein_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga", "heo", "bò", "bo", 
        "lươn", "luon", "meat", "fish", "chicken", "pork", "beef", 
        "xúc xích", "xuc xich", "sausage", "giò", "gio", "trứng", "trung", "egg",
        "ba rọi", "ba roi", "pork belly", "sườn", "suon", "rib", "bì", "bi",
        "ếch", "ech", "frog", "ngâm", "ngam", "pickled"
    ]
    if any(kw in dish_name or kw in dish_type for kw in protein_keywords):
        return False
    
    # Exclude bean dishes cooked with protein
    if "đậu" in dish_name or "dau" in dish_name:
        cooking_keywords = ["xào", "xao", "kho", "chiên", "chien", "nướng", "nuong", "rang"]
        if any(kw in dish_name or kw in dish_type for kw in cooking_keywords):
            return False
    
    # Exclude gỏi/salad with protein
    if "gỏi" in dish_name or "goi" in dish_name or ("salad" in dish_name and any(kw in dish_name for kw in protein_keywords)):
        return False
    
    veg_keywords = [
        "rau", "cải", "cai", "xà lách", "xa lach",
        "vegetable", "greens", "cucumber", "dưa chuột", "dua chuot"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in veg_keywords)


def _is_fruit(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a fruit (trái cây) - pure fruit, not gỏi or salad."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # Exclude combined dishes, main dishes, and gỏi
    if _is_combined_dish(recipe) or _is_main_dish(recipe):
        return False
    
    if "gỏi" in dish_name or "goi" in dish_name:
        return False
    
    # Exclude breakfast items
    breakfast_keywords = ["bánh", "banh", "pancake", "flan", "cake", "bánh bông lan", "banh bong lan"]
    if any(kw in dish_name or kw in dish_type for kw in breakfast_keywords):
        return False
    
    # Exclude dishes with protein keywords
    protein_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga", "heo", "bò", "bo", 
        "lươn", "luon", "meat", "fish", "chicken", "pork", "beef", 
        "xúc xích", "xuc xich", "sausage", "giò", "gio", "bì", "bi", 
        "ngâm", "ngam", "pickled", "kho", "chiên", "chien", "xào", "xao",
        "rang", "nướng", "nuong", "vây", "vay", "fin", "rim", "rim",
        "ba rọi", "ba roi", "pork belly", "sườn", "suon", "rib", "ếch", "ech", "frog",
        "khoai tây", "khoai tay", "potato", "khoai lang", "khoai lang", "sweet potato"
    ]
    if any(kw in dish_name or kw in dish_type for kw in protein_keywords):
        return False
    
    # Pure fruit keywords
    fruit_keywords = [
        "trái cây", "trai cay", "fruit", "chuối", "chuoi", "táo", "tao",
        "cam", "ổi", "oi", "dưa hấu", "dua hau", "watermelon", "apple", "orange",
        "detox", "smoothie", "nước ép", "nuoc ep", "juice"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in fruit_keywords)


def _is_combined_dish(recipe: Dict[str, Any]) -> bool:
    """
    Check if recipe is a combined dish (có cả carb và protein trong cùng một món).
    Vietnamese examples: mì trộn, bún trộn, cơm chiên, cơm rang, phở, bún bò, bánh canh, cháo...
    """
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    combined_keywords = [
        "mì trộn", "mi tron", "bún trộn", "bun tron", "phở", "pho", "bún bò", "bun bo",
        "bún chả", "bun cha", "bún riêu", "bun rieu", "bánh canh", "banh canh",
        "cơm chiên", "com chien", "cơm rang", "com rang", "fried rice",
        "cơm xay", "com xay", "cơm với", "com voi", "rice with",
        "cháo", "chao", "porridge",
        "bánh mì", "banh mi", "sandwich", "salad", "gỏi", "goi",
    ]
    
    if any(kw in dish_name or kw in dish_type for kw in combined_keywords):
        return True
    
    # Check if it contains both carb keywords AND protein keywords
    carb_keywords = ["mì", "mi", "bún", "bun", "phở", "pho", "cơm", "com", "cháo", "chao", "bánh canh", "banh canh", "salad", "gỏi", "goi"]
    protein_keywords = ["thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga", "heo", "bò", "bo", "lươn", "luon", "meat", "fish", "chicken", "pork", "beef", "xúc xích", "xuc xich", "sausage", "giò", "gio"]
    
    has_carb = any(kw in dish_name or kw in dish_type for kw in carb_keywords)
    has_protein = any(kw in dish_name or kw in dish_type for kw in protein_keywords)
    
    if has_carb and has_protein:
        # Exclude plain white rice
        if _is_rice_dish(recipe):
            if "cơm trắng" in dish_name or "com trang" in dish_name or "white rice" in dish_name:
                if not any(kw in dish_name for kw in ["chiên", "chien", "rang", "fried", "xay", "với", "voi", "with"]):
                    return False
            return True
        return True
    
    return False


def _is_carb_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a carb dish (rice/noodle/soup)."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    carb_keywords = [
        "cơm", "com", "rice", "phở", "pho", "bún", "bun", "mì", "mi",
        "noodle", "soup", "canh", "cháo", "chao"
    ]
    
    return any(keyword in dish_name or keyword in dish_type for keyword in carb_keywords)


def _matches_meal_slot(recipe: Dict[str, Any], slot: str) -> bool:
    """Check if recipe matches meal slot (breakfast/lunch/dinner)."""
    slot = slot.lower()
    dish_type = recipe.get("dish_type")
    meal_type = recipe.get("meal_type")

    # Check explicit meal_type field
    if isinstance(meal_type, str):
        if slot in meal_type.lower():
            return True
    
    # Check dish_type field
    if isinstance(dish_type, str):
        if slot in dish_type.lower():
            return True
    if isinstance(dish_type, list):
        if any(slot in str(entry).lower() for entry in dish_type):
            return True

    # Vietnamese breakfast detection
    if slot == "breakfast" or slot == "sáng":
        return _is_vietnamese_breakfast(recipe)
    
    # For lunch/dinner, exclude breakfast dishes
    if slot in ["lunch", "dinner", "trưa", "tối"]:
        return not _is_vietnamese_breakfast(recipe)
    
    return False


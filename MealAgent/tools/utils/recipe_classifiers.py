"""
Recipe classification functions for meal planning.
Centralized to avoid duplication across tools.
"""

from typing import Dict, Any


def _is_vietnamese_breakfast(recipe: Dict[str, Any]) -> bool:
    """
    Check if recipe is a Vietnamese breakfast dish.
    
    Vietnamese breakfast dishes typically include:
    - Phở, bún, hủ tiếu, mì, miến, bánh canh (noodles)
    - Bánh mì, bánh ngọt, xôi, bánh (breads, cakes, sticky rice)
    - Cơm tấm (broken rice)
    - Cháo (porridge)
    - Ngô/khoai luộc (boiled corn/sweet potato)
    - Súp (soup)
    """
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # CRITICAL: Vietnamese breakfast keywords - dishes that start with these are breakfast
    # User requirement: bún, hủ tiếu, bánh mì, mì, phở, miến, bánh canh, bánh ngọt, bánh mặn, 
    # xôi, bánh cuốn, các loại bánh, cơm tấm, cháo, ngô/khoai luộc, súp
    breakfast_keywords = [
        # Noodles (bún, hủ tiếu, mì, phở, miến, bánh canh)
        "phở", "pho", "bun", "bún", "bun bo", "bún bò", "bun rieu", "bún riêu", 
        "bun cha", "bún chả", "bun thang", "bún thang", "bun oc", "bún ốc",
        "hu tieu", "hủ tiếu", "hu tiu", "hủ tiu", "hủ tiếu", "hu tieu",
        "mì", "mi", "miến", "mien", "mì soba", "mi soba",
        "banh canh", "bánh canh",
        # Breads and cakes (bánh mì, bánh ngọt, bánh mặn, bánh cuốn, các loại bánh)
        "banh mi", "bánh mì", "banh ngot", "bánh ngọt", "banh man", "bánh mặn",
        "banh bao", "bánh bao", "banh cuon", "bánh cuốn", "banh xeo", "bánh xèo",
        "banh", "bánh",  # General cake/bread (but check context)
        # Sticky rice (xôi)
        "xoi", "xôi", "xoi man", "xôi mặn", "xoi ngo", "xôi ngô", "xoi gac", "xôi gấc",
        # Rice dishes (cơm tấm)
        "cơm tấm", "com tam", "com suon", "cơm sườn",
        # Porridge (cháo)
        "chao", "cháo", "chao ga", "cháo gà", "chao bo", "cháo bò",
        # Boiled items (ngô/khoai luộc)
        "ngô luộc", "ngo luoc", "khoai luoc", "khoai luộc", "ngô", "ngo", "khoai", "khoai lang",
        # Soup (súp)
        "súp", "sup", "soup",
        # Western breakfast items (also common in Vietnam)
        "sandwich", "croissant", "brioche", "toast", "pancake", "trứng chiên", "trung chien"
    ]
    
    # Check if dish name starts with or contains breakfast keywords
    dish_name_lower = dish_name.lower().strip()
    
    # CRITICAL: Exclude main dishes that are NOT breakfast (e.g., "Ba Chỉ Và Mực Nướng Sữa Đặc")
    # Main dish keywords that should NOT be breakfast
    main_dish_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga", "heo", "bò", "bo",
        "meat", "fish", "chicken", "pork", "beef", "kho", "nướng", "nuong", 
        "rang", "xào", "xao", "chiên", "chien", "sườn", "suon", "mực", "muc"
    ]
    
    # CRITICAL: Exclude main dishes that are NOT breakfast
    # Check if dish name starts with or contains main dish keywords (not breakfast)
    for main_keyword in main_dish_keywords:
        # Check startswith first (most common case)
        if dish_name_lower.startswith(main_keyword):
            return False  # This is a main dish, not breakfast
        # Also check if keyword appears prominently in the name (not just as part of another word)
        # For example: "Ba Chỉ Và Mực Nướng" contains "mực" and "nướng"
        if len(main_keyword) >= 3 and main_keyword in dish_name_lower:
            # Additional check: if it's a standalone word or part of a compound dish name
            # This helps catch cases like "mực nướng", "thịt kho", etc.
            return False  # This is likely a main dish, not breakfast
    
    # Check breakfast keywords
    for keyword in breakfast_keywords:
        # CRITICAL: For "banh" or "bánh", be more specific - only match if it's a breakfast bread/cake
        if keyword in ["banh", "bánh"]:
            # Only match if it's a specific breakfast bread/cake (banh mi, banh bao, etc.)
            if keyword in dish_name_lower:
                # Check if it's a breakfast bread/cake (banh mi, banh bao, banh cuon, banh xeo, banh ngot)
                breakfast_bread_keywords = ["banh mi", "bánh mì", "banh bao", "bánh bao", "banh cuon", "bánh cuốn", 
                                           "banh xeo", "bánh xèo", "banh ngot", "bánh ngọt", "banh canh", "bánh canh"]
                if any(bread_kw in dish_name_lower for bread_kw in breakfast_bread_keywords):
                    return True
                # Otherwise, don't match generic "banh" to avoid false positives
                continue
        
        # Check if dish name starts with the keyword (most common case)
        if dish_name_lower.startswith(keyword):
            return True
        # Also check if keyword is in the dish name (for compound names)
        if keyword in dish_name_lower:
            return True
    
    # Check dish_type field
    if any(keyword in dish_type for keyword in breakfast_keywords):
        return True
    
    # Check meal_type field
    meal_type = str(recipe.get("meal_type", "")).lower()
    if "breakfast" in meal_type or "sáng" in meal_type or "buổi sáng" in meal_type:
        return True
    
    return False


def _is_rice_dish(recipe: Dict[str, Any]) -> bool:
    """Check if recipe is a rice dish (cơm) - plain rice, not main dishes."""
    dish_name = str(recipe.get("dish_name", "")).lower()
    dish_type = str(recipe.get("dish_type", "")).lower()
    
    # CRITICAL: Rice dishes must explicitly contain "cơm" or "com" or "rice"
    rice_keywords = ["cơm", "com", "rice"]
    has_rice = any(keyword in dish_name or keyword in dish_type for keyword in rice_keywords)
    
    if not has_rice:
        return False
    
    # CRITICAL: Exclude main dishes - if dish contains main ingredients, it's NOT plain rice
    main_keywords = [
        "thịt", "thit", "cá", "ca", "tôm", "tom", "gà", "ga",
        "heo", "bò", "bo", "meat", "fish", "chicken", "pork", "beef",
        "kho", "nướng", "nuong", "rang", "xào", "xao", "chiên", "chien",
        "sườn", "suon", "mực", "muc", "tôm", "tom", "cua", "crab",
        "lẩu", "lau", "nướng", "nuong", "cuốn", "cuon"
    ]
    has_main_keywords = any(keyword in dish_name or keyword in dish_type for keyword in main_keywords)
    
    # If it has main keywords, it's likely a main dish (even if it has "cơm" in name like "Cơm Gà")
    # Only allow if it's explicitly "Cơm Trắng" (white rice) or similar plain rice
    if has_main_keywords:
        # Allow only if it's a simple rice dish name like "Cơm Trắng", "Cơm", "Rice"
        plain_rice_names = ["cơm trắng", "com trang", "cơm", "com", "rice", "white rice"]
        if not any(plain_name in dish_name for plain_name in plain_rice_names):
            return False  # This is a main dish with rice, not plain rice
    
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
    
    # Exclude soup dishes (canh) - they are accompaniments, not rice
    if "canh" in dish_name or "canh" in dish_type:
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


import re
from typing import Dict, Any, Optional, Tuple

# Default weights for discrete units (grams)
DEFAULT_UNIT_WEIGHTS = {
    "củ": 80.0,
    "quả": 100.0,
    "trái": 100.0,
    "tép": 5.0,
    "miếng": 50.0,
    "con": 200.0,
    "chén": 200.0,
    "bát": 200.0,
    "muỗng": 15.0,
    "thìa": 5.0,
    "bó": 200.0,
    "nhánh": 10.0,
    "lát": 20.0,
    "gói": 100.0,
    "hộp": 250.0,
    "lon": 330.0,
    "chai": 500.0,
    "hũ": 100.0,
    "khay": 300.0,
    "bịch": 100.0,
    "ổ": 100.0,
}

# Unit normalization mapping
UNIT_MAPPING = {
    "kg": "kg",
    "kgs": "kg",
    "kilogram": "kg",
    "g": "g",
    "gr": "g",
    "gram": "g",
    "grams": "g",
    "ml": "ml",
    "l": "l",
    "liter": "l",
    "tép": "tép",
    "củ": "củ",
    "quả": "quả",
    "trái": "quả",
    "miếng": "miếng",
    "con": "con",
    "chén": "chén",
    "bát": "chén",
    "muỗng": "muỗng",
    "thìa": "thìa",
    "bó": "bó",
    "nhánh": "nhánh",
    "lát": "lát",
}

def parse_vietnamese_number(num_str: str) -> Optional[float]:
    """Parse numeric string including decimals (with . or ,) and fractions."""
    if not num_str:
        return None
    
    # Clean string
    num_str = num_str.strip().replace(",", ".")
    
    # Handle fractions (e.g., 1/2)
    if "/" in num_str:
        parts = num_str.split("/")
        if len(parts) == 2:
            try:
                numerator = float(parts[0])
                denominator = float(parts[1])
                if denominator != 0:
                    return numerator / denominator
            except ValueError:
                pass
    
    # Handle pure numbers
    try:
        return float(num_str)
    except ValueError:
        return None

def parse_ingredient_string(text: str) -> Dict[str, Any]:
    """
    Parse a Vietnamese ingredient string into name, quantity, and unit.
    Example: "500g Cá rô phi" -> {"name": "cá rô phi", "quantity": 500.0, "unit": "g"}
    Example: "1/2 chén gạo" -> {"name": "gạo", "quantity": 0.5, "unit": "chén"}
    """
    if not text:
        return {"name": "", "quantity": 0.0, "unit": "g"}

    text = text.strip()
    
    # Regex for quantity and unit at the beginning or end
    # Supports: 500g, 1.2kg, 1/2 chén, 10 gr, etc.
    quantity_pattern = r"(?P<num>[\d.,/]+)\s*(?P<unit>[a-zA-Zà-ỹ]+)"
    
    match = re.search(quantity_pattern, text, re.IGNORECASE)
    
    quantity = 1.0  # Default if no number found
    unit = "g"      # Default unit
    clean_name = text
    
    if match:
        num_str = match.group("num")
        raw_unit = match.group("unit").lower().strip()
        
        parsed_num = parse_vietnamese_number(num_str)
        if parsed_num is not None:
            quantity = round(parsed_num, 3)
            
            # Normalize unit
            normalized_unit = UNIT_MAPPING.get(raw_unit, raw_unit)
            unit = normalized_unit
            
            # Remove from name
            # We use string replace for simplicity but careful about partial matches
            # A safer way is using the match span
            start, end = match.span()
            clean_name = (text[:start] + text[end:]).strip(" ,:.-")
    
    # If no unit found, try to find unit without number (e.g., "Hành lá: 3")
    # This happens sometimes in the user's data
    if not match:
        alt_match = re.search(r":\s*(?P<num>[\d.,/]+)", text)
        if alt_match:
            parsed_num = parse_vietnamese_number(alt_match.group("num"))
            if parsed_num is not None:
                quantity = parsed_num
                clean_name = text[:alt_match.start()].strip(" ,:.-")

    # Final cleanup of the name
    clean_name = re.sub(r"^\s*-\s*", "", clean_name) # Remove leading dash
    clean_name = clean_name.lower().strip(" ,:.-")
    
    return {
        "name": clean_name,
        "quantity": quantity,
        "unit": unit
    }

def convert_to_grams(quantity: float, unit: str) -> float:
    """Convert a quantity with a given unit to grams."""
    unit = unit.lower()
    if unit == "g":
        return quantity
    if unit == "kg":
        return quantity * 1000.0
    if unit == "ml":
        return quantity  # Assume 1ml = 1g
    if unit == "l":
        return quantity * 1000.0
    
    # Discrete units
    weight = DEFAULT_UNIT_WEIGHTS.get(unit, 1.0)
    return quantity * weight

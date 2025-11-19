import argparse, csv, json, ast, os
from typing import Any, Dict, List, Optional
import weaviate
from weaviate.classes.query import QueryReference, Filter, MetadataQuery
from weaviate.util import generate_uuid5

# ==============================
# Connection (defaults for local)
# ==============================

def connect():
    # Sửa tại đây nếu bạn không dùng cổng mặc định
    return weaviate.connect_to_local(host="localhost", port=8078, grpc_port=50051)

def must_file(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing file: {path}")
    return path

# ==============================
# Small helpers
# ==============================

def to_str(x: Any) -> str:
    return "" if x is None else str(x).strip()

def to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in {"na", "nan", "none", "null"}:
        return None
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        return None

def to_int(x: Any) -> Optional[int]:
    if x is None:
        return None
    s = str(x).strip()
    if s == "" or s.lower() in {"na", "nan", "none", "null"}:
        return None
    s = s.replace(",", "")
    try:
        return int(float(s))
    except Exception:
        return None

def parse_listish(s: Any) -> List[dict]:
    """Accept JSON string or Python literal list of dicts, else []."""
    if s is None:
        return []
    if isinstance(s, list):
        return s
    raw = str(s).strip()
    if raw == "":
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return v
    except Exception:
        pass
    try:
        v = ast.literal_eval(raw)
        if isinstance(v, list):
            return v
    except Exception:
        pass
    return []

def norm_mu_name(x: Any) -> str:
    return (str(x) if x is not None else "").strip()

# Deterministic UUIDs for idempotent upsert
def uuid_food(fdc_id: str) -> str:
    return generate_uuid5(f"FdcFood:{fdc_id}")

def uuid_nutrient(fdc_id: str, nutrient_id: Any) -> str:
    return generate_uuid5(f"FdcNutrient:{fdc_id}:{nutrient_id}")

def uuid_portion(fdc_id: str, payload: Dict[str, Any]) -> str:
    amt = to_str(payload.get("amount"))
    mu  = to_str(payload.get("measure_unit") or payload.get("unit") or payload.get("measureUnit"))
    gw  = to_str(payload.get("gram_weight") or payload.get("gramWeight"))
    return generate_uuid5(f"FdcPortion:{fdc_id}:{amt}:{mu}:{gw}")

# ==============================
# Column detection (flexible header mapping)
# ==============================

FOOD_KEY_SYNONYMS = ["fdc_id", "FDC_ID", "fdcId", "id"]
DESC_SYNONYMS     = ["description", "food_description", "name", "long_desc", "food_name"]

FOOD_SCALARS = {
    # Macros (per 100g)
    "energy_kcal_100g":      {"syn": ["energy_kcal_100g", "kcal_100g", "energy_kcal", "energy_kcal_per_100g"]},
    "protein_g_100g":        {"syn": ["protein_g_100g", "protein_100g", "protein_per_100g"]},
    "fat_g_100g":            {"syn": ["fat_g_100g", "total_fat_g_100g", "fat_100g", "fat_per_100g"]},
    "carbohydrate_g_100g":   {"syn": ["carbohydrate_g_100g", "carbs_g_100g", "carb_g_100g", "carbohydrate_100g", "carbohydrate_per_100g"]},
    "sugars_g_100g":         {"syn": ["sugars_g_100g", "sugar_g_100g", "sugars_100g", "sugars_per_100g"]},
    "fiber_g_100g":          {"syn": ["fiber_g_100g", "dietary_fiber_g_100g", "fiber_100g", "fiber_per_100g"]},
    "sodium_mg_100g":        {"syn": ["sodium_mg_100g", "sodium_100g", "na_mg_100g", "sodium_per_100g"]},
    "sat_fat_g_100g":        {"syn": ["sat_fat_g_100g", "saturated_fat_g_100g", "sfa_g_100g", "saturated_fat_per_100g"]},

    # Micros (per 100g)
    "calcium_mg_100g":       {"syn": ["calcium_mg_100g", "calcium_100g", "calcium_per_100g"]},
    "iron_mg_100g":          {"syn": ["iron_mg_100g", "iron_100g", "iron_per_100g"]},
    "potassium_mg_100g":     {"syn": ["potassium_mg_100g", "potassium_100g", "potassium_per_100g"]},
    "magnesium_mg_100g":     {"syn": ["magnesium_mg_100g", "magnesium_100g", "magnesium_per_100g"]},
    "zinc_mg_100g":          {"syn": ["zinc_mg_100g", "zinc_100g", "zinc_per_100g"]},
    "vitamin_a_rae_ug_100g": {"syn": ["vitamin_a_rae_ug_100g", "vitamin_a_rae_100g", "vitamin_a_per_100g"]},
    "vitamin_b6_mg_100g":    {"syn": ["vitamin_b6_mg_100g", "vitamin_b6_100g", "vitamin_b6_per_100g"]},
    "vitamin_b12_ug_100g":   {"syn": ["vitamin_b12_ug_100g", "vitamin_b12_100g", "vitamin_b12_per_100g"]},
    "thiamin_b1_mg_100g":    {"syn": ["thiamin_b1_mg_100g", "thiamin_mg_100g", "vitamin_b1_mg_100g"]},
    "riboflavin_b2_mg_100g": {"syn": ["riboflavin_b2_mg_100g", "riboflavin_mg_100g", "vitamin_b2_mg_100g"]},
    "niacin_b3_mg_100g":     {"syn": ["niacin_b3_mg_100g", "niacin_mg_100g", "vitamin_b3_mg_100g"]},
    "vitamin_c_mg_100g":     {"syn": ["vitamin_c_mg_100g", "vitamin_c_100g", "vitamin_c_per_100g"]},
    "vitamin_d_ug_100g":     {"syn": ["vitamin_d_ug_100g", "vitamin_d_100g", "vitamin_d_per_100g"]},
    "vitamin_e_mg_100g":     {"syn": ["vitamin_e_mg_100g", "vitamin_e_100g", "vitamin_e_per_100g"]},
}

NUTRIENTS_LIST_COLS = ["nutrients_json", "nutrients", "nutrient_json", "nutrients_list"]
PORTIONS_LIST_COLS  = ["portions_json", "portions", "portion_json", "portions_list"]

# Map USDA nutrient_id → FdcFood scalar property name (per 100g)
NUTRIENT_IDS = {
    1008: "energy_kcal_100g",
    1003: "protein_g_100g",
    1004: "fat_g_100g",
    1005: "carbohydrate_g_100g",
    2000: "sugars_g_100g",
    1079: "fiber_g_100g",
    1093: "sodium_mg_100g",
    1258: "sat_fat_g_100g",
    # Minerals
    1087: "calcium_mg_100g",
    1089: "iron_mg_100g",
    1092: "potassium_mg_100g",
    1090: "magnesium_mg_100g",
    1095: "zinc_mg_100g",
    # Vitamins
    1106: "vitamin_a_rae_ug_100g",
    1175: "vitamin_b6_mg_100g",
    1178: "vitamin_b12_ug_100g",
    1165: "thiamin_b1_mg_100g",
    1166: "riboflavin_b2_mg_100g",
    1167: "niacin_b3_mg_100g",
    1162: "vitamin_c_mg_100g",
    1114: "vitamin_d_ug_100g",
    1109: "vitamin_e_mg_100g",
}

# Default units per nutrient_id (per 100g)
NUTRIENT_UNITS = {
    1008: "kcal",
    1003: "g",
    1004: "g",
    1005: "g",
    2000: "g",
    1079: "g",
    1093: "mg",
    1258: "g",
    1087: "mg",
    1089: "mg",
    1092: "mg",
    1090: "mg",
    1095: "mg",
    1106: "ug",
    1175: "mg",
    1178: "ug",
    1165: "mg",
    1166: "mg",
    1167: "mg",
    1162: "mg",
    1114: "ug",
    1109: "mg",
}

def find_first_col(header: List[str], candidates: List[str]) -> Optional[str]:
    lower = {h.lower(): h for h in header}
    for cand in candidates:
        if cand.lower() in lower:
            return lower[cand.lower()]
    return None

def match_scalar_cols(header: List[str]) -> Dict[str, str]:
    lower = {h.lower(): h for h in header}
    out = {}
    for canon, spec in FOOD_SCALARS.items():
        for syn in spec["syn"]:
            if syn.lower() in lower:
                out[canon] = lower[syn.lower()]
                break
    return out

# ==============================
# Ingest from flat CSV
# ==============================

def ingest_from_flat_csv(client, csv_path: str, batch_size: int = 1000):
    foods_col     = client.collections.get("FdcFood")
    nutrients_col = client.collections.get("FdcNutrient")
    portions_col  = client.collections.get("FdcPortion")

    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        fdc_col   = find_first_col(header, FOOD_KEY_SYNONYMS)
        desc_col  = find_first_col(header, DESC_SYNONYMS)
        scalar_map = match_scalar_cols(header)
        nutrients_colname = find_first_col(header, NUTRIENTS_LIST_COLS)
        portions_colname  = find_first_col(header, PORTIONS_LIST_COLS)
        if not fdc_col:
            raise ValueError(f"Không tìm thấy cột fdc_id trong {header}")

    # 1) FdcFood
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        with foods_col.batch.fixed_size(batch_size=batch_size) as batch_food:
            for row in reader:
                fdc_id_raw = row.get(fdc_col)
                fdc_id = to_str(fdc_id_raw)
                if not fdc_id:
                    continue
                fdc_id_int = to_int(fdc_id)
                if fdc_id_int is None:
                    continue
                desc = to_str(row.get(desc_col)) if desc_col else ""
                # Initialize all scalar fields to None; fill those found in CSV
                props = {"fdc_id": fdc_id_int, "description": desc}
                for canon in FOOD_SCALARS.keys():
                    props[canon] = None
                for canon, col in scalar_map.items():
                    props[canon] = to_float(row.get(col))
                batch_food.add_object(properties=props, uuid=uuid_food(fdc_id))
                if batch_food.number_errors > 50:
                    raise RuntimeError("Too many errors while inserting FdcFood")

    # 2) FdcNutrient
    # Accumulate per-food scalar values from nutrients for later update
    fdc_scalar_accum: Dict[str, Dict[str, float]] = {}

    if nutrients_colname:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            with nutrients_col.batch.fixed_size(batch_size=batch_size) as batch_nut:
                for row in reader:
                    fdc_id_raw = row.get(fdc_col)
                    fdc_id = to_str(fdc_id_raw)
                    if not fdc_id:
                        continue
                    fdc_id_int = to_int(fdc_id)
                    if fdc_id_int is None:
                        continue
                    for item in parse_listish(row.get(nutrients_colname)):
                        nid  = item.get("nutrient_id") or item.get("nutrientId") or item.get("id")
                        amt  = item.get("amount_100g") or item.get("amount") or item.get("value")
                        unit = item.get("unit") or item.get("unit_name") or item.get("unitName")
                        if nid is None:
                            continue
                        nid_int = int(nid)
                        props = {
                            "fdc_id": fdc_id_int,
                            "nutrient_id": nid_int,
                            "amount_100g": to_float(amt),
                            "unit": to_str(unit) or NUTRIENT_UNITS.get(nid_int, ""),
                            "nutrient_name": NUTRIENT_IDS.get(nid_int),
                        }
                        batch_nut.add_object(properties=props, uuid=uuid_nutrient(fdc_id, int(nid)))
                        if batch_nut.number_errors > 200:
                            raise RuntimeError("Too many errors while inserting FdcNutrient")

                        # Enrich accumulator for FdcFood scalar fields
                        try:
                            nid_int = int(nid)
                            field_name = NUTRIENT_IDS.get(nid_int)
                            val = to_float(amt)
                            if field_name and val is not None:
                                acc = fdc_scalar_accum.setdefault(fdc_id, {})
                                acc[field_name] = val
                        except Exception:
                            pass

    # 3) FdcPortion (+ index các UUID để nối ref)
    portion_uuid_index: Dict[str, List[str]] = {}
    if portions_colname:
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            with portions_col.batch.fixed_size(batch_size=batch_size) as batch_portion:
                for row in reader:
                    fdc_id_raw = row.get(fdc_col)
                    fdc_id = to_str(fdc_id_raw)
                    if not fdc_id:
                        continue
                    fdc_id_int = to_int(fdc_id)
                    if fdc_id_int is None:
                        continue
                    uuids = []
                    for item in parse_listish(row.get(portions_colname)):
                        props = {
                            "fdc_id": fdc_id_int,
                            "amount": to_float(item.get("amount")),
                            "measure_unit": norm_mu_name(item.get("measure_unit") or item.get("unit") or item.get("measureUnit")),
                            "gram_weight": to_float(item.get("gram_weight") or item.get("gramWeight")),
                        }
                        p_uuid = uuid_portion(fdc_id, props)
                        uuids.append(p_uuid)
                        batch_portion.add_object(properties=props, uuid=p_uuid)
                        if batch_portion.number_errors > 200:
                            raise RuntimeError("Too many errors while inserting FdcPortion")
                    if uuids:
                        portion_uuid_index[fdc_id] = uuids

    # 4) Wire references (FdcFood -> has_nutrient / has_portion)
    foods_col = client.collections.get("FdcFood")
    with foods_col.batch.fixed_size(batch_size=batch_size) as batch_ref:
        if nutrients_colname:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    fdc_id = to_str(row.get(fdc_col))
                    if not fdc_id:
                        continue
                    for item in parse_listish(row.get(nutrients_colname)):
                        nid = item.get("nutrient_id") or item.get("nutrientId") or item.get("id")
                        if nid is None:
                            continue
                        batch_ref.add_reference(
                            from_uuid=uuid_food(fdc_id),
                            from_property="has_nutrient",
                            to=uuid_nutrient(fdc_id, int(nid)),
                        )
        for fdc_id, plist in portion_uuid_index.items():
            for p_uuid in plist:
                batch_ref.add_reference(
                    from_uuid=uuid_food(fdc_id),
                    from_property="has_portion",
                    to=p_uuid,
                )
        if batch_ref.number_errors > 100:
            raise RuntimeError("Too many errors while wiring references")

    # 5) Update FdcFood scalar fields from accumulated nutrients
    if fdc_scalar_accum:
        for fdc_id, fields in fdc_scalar_accum.items():
            if not fields:
                continue
            try:
                foods_col.data.update(uuid=uuid_food(fdc_id), properties=fields)
            except Exception:
                # best-effort; skip if update fails for specific item
                pass

# ==============================
# Verify (gọn)
# ==============================

def verify_ingested_data(client, sample_size: int = 10):
    foods     = client.collections.get("FdcFood")
    nutrients = client.collections.get("FdcNutrient")
    portions  = client.collections.get("FdcPortion")

    print("\n📊 Collection Statistics:")
    print("   FdcFood    :", foods.aggregate.over_all(total_count=True).total_count)
    print("   FdcNutrient:", nutrients.aggregate.over_all(total_count=True).total_count)
    print("   FdcPortion :", portions.aggregate.over_all(total_count=True).total_count)

    print(f"\n🍎 Sample FdcFood (first {sample_size} with refs):")
    res = foods.query.fetch_objects(
        limit=sample_size,
        include_vector=False,
        return_references=[
            QueryReference(link_on="has_nutrient", return_properties=["nutrient_id","amount_100g","unit"]),
            QueryReference(link_on="has_portion" , return_properties=["amount","measure_unit","gram_weight"]),
        ],
        return_metadata=MetadataQuery(),
    )
    for i, o in enumerate(res.objects, 1):
        p = o.properties or {}
        desc = (p.get("description") or "")
        if len(desc) > 80: desc = desc[:80] + "..."
        nut_objs  = getattr((o.references or {}).get("has_nutrient"), "objects", []) or []
        port_objs = getattr((o.references or {}).get("has_portion"),  "objects", []) or []
        print(f"\n   [{i}] {p.get('fdc_id')} — {desc}")
        print(f"        kcal/100g={p.get('energy_kcal_100g')} | protein_g_100g={p.get('protein_g_100g')}")
        print(f"        nutrients: {len(nut_objs)} | portions: {len(port_objs)}")

    print("\n🔧 Quick integrity:")
    without_nut = foods.aggregate.over_all(
        total_count=True,
        filters=Filter.by_ref_count("has_nutrient").equal(0)
    ).total_count
    print(f"   Foods without nutrients: {without_nut}")

# ==============================
# Show 10 rows for a collection
# ==============================

def show_collection_rows(client, name: str, limit: int = 10):
    col = client.collections.get(name)
    refs = None
    if name == "FdcFood":
        refs = [QueryReference(link_on="has_nutrient"), QueryReference(link_on="has_portion")]
    res = col.query.fetch_objects(limit=limit, include_vector=False, return_references=refs)
    print(f"\n📄 {name}: showing {len(res.objects)} rows")
    for i, obj in enumerate(res.objects, 1):
        props = obj.properties or {}
        print(f"\n[{i}] id={obj.uuid}")
        for k, v in props.items():
            print(f"   {k}: {v}")
        if refs:
            for rn in ("has_nutrient","has_portion"):
                r = (obj.references or {}).get(rn)
                linked = len(getattr(r, "objects", []) or [])
                print(f"   ↳ {rn}: {linked} linked")

# ==============================
# CLI (tối giản)
# ==============================

def main():
    ap = argparse.ArgumentParser(description="Ingest FDC CSV -> FdcFood/FdcNutrient/FdcPortion (minimal CLI)")
    ap.add_argument("--csv", help="Path tới FDC_data.csv để ingest")
    ap.add_argument("--verify", action="store_true", help="Kiểm tra nhanh dữ liệu sau ingest")
    ap.add_argument("--show", choices=["FdcFood","FdcNutrient","FdcPortion"], help="Xem 10 dòng đầu của collection")
    args = ap.parse_args()

    with connect() as client:
        if args.show and not args.csv:
            show_collection_rows(client, args.show, limit=10)
            return

        ran_any = False

        if args.csv:
            ingest_from_flat_csv(client, must_file(args.csv), batch_size=1000)
            print("✅ Ingest completed.")
            ran_any = True

        if args.verify:
            verify_ingested_data(client, sample_size=10)
            ran_any = True

        if ran_any:
            return

        ap.error("Specify: --csv <path> (optional with --verify) | --show {FdcFood|FdcNutrient|FdcPortion} | --verify")

if __name__ == "__main__":
    main()

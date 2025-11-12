# ingest_recipes_big.py
import argparse, csv, json, ast, os, gzip, io, time, sys
from typing import Any, Dict, List, Optional
import weaviate
from weaviate.util import generate_uuid5

# --------------------------
# Kết nối (local by default)
# --------------------------
def connect():
    return weaviate.connect_to_local(host="localhost", port=8078, grpc_port=50051)

def must_file(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Missing file: {path}")
    return path

# --------------------------
# Helpers
# --------------------------
ID_SYNS    = ["food_id", "recipe_id", "id", "recipeId"]
TITLE_SYNS = ["dish_name", "title", "name"]
INGR_SYNS  = ["ingredients", "ings", "ingredient_list", "ingredients_array"]
DIRS_SYNS  = ["cooking_method_array", "directions", "steps", "instructions"]

def to_str(x: Any) -> str:
    return "" if x is None else str(x).strip()

def parse_listish(s: Any) -> List[str]:
    if s is None:
        return []
    if isinstance(s, list):
        return [to_str(x) for x in s if to_str(x)]
    raw = to_str(s)
    if raw == "":
        return []
    # JSON
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [to_str(x) for x in v if to_str(x)]
    except Exception:
        pass
    # Python literal
    try:
        v = ast.literal_eval(raw)
        if isinstance(v, list):
            return [to_str(x) for x in v if to_str(x)]
    except Exception:
        pass
    # Split fallback
    parts: List[str] = []
    for chunk in raw.replace("||", "\n").replace("|", "\n").replace(";", "\n").splitlines():
        t = to_str(chunk)
        if t:
            parts.append(t)
    return parts

def find_col(header: List[str], syns: List[str]) -> Optional[str]:
    lower = {h.lower(): h for h in header}
    for s in syns:
        if s.lower() in lower:
            return lower[s.lower()]
    return None

def uuid_recipe(recipe_id: str) -> str:
    return generate_uuid5(f"Recipe:{recipe_id}")

def open_maybe_gzip(path: str):
    # Tự phát hiện .gz, trả về file-like text stream (utf-8-sig)
    if path.lower().endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8-sig", newline="")
    return open(path, "r", encoding="utf-8-sig", newline="")

# --------------------------
# Progress log helpers
# --------------------------
def human_sec(s: float) -> str:
    s = int(s)
    if s < 60: return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60: return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"

def print_progress(processed: int, start_ts: float, max_rows: Optional[int] = None, prefix: str = ""):
    elapsed = time.time() - start_ts
    rate = processed / elapsed if elapsed > 0 else 0.0
    if max_rows is not None and processed > 0:
        remain = max_rows - processed
        eta = remain / rate if rate > 0 else 0
        eta_str = human_sec(eta)
    else:
        eta_str = "--"
    msg = f"{prefix} processed={processed:,}  elapsed={human_sec(elapsed)}  rate={rate:,.1f} rows/s  ETA={eta_str}"
    print(msg, flush=True)

# --------------------------
# Ingest (streaming + resume + progress)
# --------------------------
def ingest_recipes_csv(
    client,
    csv_path: str,
    batch_size: int = 400,
    start_line: int = 2,
    max_rows: Optional[int] = None,
    checkpoint_file: Optional[str] = None,
    checkpoint_every: int = 20000,
    log_every: int = 5000,
):
    """
    start_line: số dòng thực tế trong file (1=header). Mặc định 2 để bỏ header.
    max_rows:   ingest tối đa N dòng (None = hết file).
    checkpoint_file: đường dẫn file lưu tiến độ (dòng cuối + recipe_id).
    log_every:  in log sau mỗi N dòng xử lý.
    """
    col = client.collections.get("Recipe")

    # 1) Đọc header để map cột
    with open_maybe_gzip(csv_path) as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or [] 
        id_col    = find_col(header, ID_SYNS)
        title_col = find_col(header, TITLE_SYNS)
        ingr_col  = find_col(header, INGR_SYNS)
        dirs_col  = find_col(header, DIRS_SYNS)
        # CSV-aligned fields (all optional except id and dish_name)
        dish_type_col   = find_col(header, ["dish_type"])  # TEXT
        serving_col     = find_col(header, ["serving_size"])  # INT
        cook_time_col   = find_col(header, ["cooking_time"])  # INT
        ingr_qty_col    = find_col(header, ["ingredients_with_qty", "ingredients_with_qty_array"])  # TEXT_ARRAY
        image_link_col  = find_col(header, ["image_link"])  # TEXT
    if not id_col or not title_col:
        raise ValueError(f"Thiếu cột bắt buộc. Tìm thấy: id={id_col}, dish_name={title_col}")

    # 2) Nếu có checkpoint thì override start_line
    if checkpoint_file and os.path.isfile(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as cf:
                line_s = cf.read().strip().split(",")[0]
                cp_line = int(line_s)
                if cp_line >= start_line:
                    start_line = cp_line + 1
                    print(f"↩️  Resume từ dòng {start_line} (theo checkpoint).")
        except Exception:
            pass

    print(f"🚀 Start ingest: file='{csv_path}', batch_size={batch_size}, start_line={start_line}, "
          f"max_rows={max_rows or 'ALL'}, log_every={log_every}, ckpt='{checkpoint_file or '-'}'")
    start_ts = time.time()

    processed = 0
    file_line = 0
    last_log_at = 0

    with open_maybe_gzip(csv_path) as f:
        reader = csv.DictReader(f)
        # Nhảy tới start_line (DictReader đã đọc header → bắt đầu line=2)
        file_line = 2
        while file_line < start_line:
            try:
                next(reader)
                file_line += 1
            except StopIteration:
                break

        with col.batch.fixed_size(batch_size=batch_size) as batch:
            for row in reader:
                file_line += 1
                rid = to_str(row.get(id_col))
                if not rid:
                    continue
                title = to_str(row.get(title_col))
                ings  = parse_listish(row.get(ingr_col)) if ingr_col else []
                dirs  = parse_listish(row.get(dirs_col)) if dirs_col else []
                dish_type  = to_str(row.get(dish_type_col)) if dish_type_col else ""
                serving_sz = row.get(serving_col) if serving_col else None
                cooking_tm = row.get(cook_time_col) if cook_time_col else None
                try:
                    serving_sz = int(str(serving_sz).strip()) if serving_sz not in (None, "") else None
                except Exception:
                    serving_sz = None
                try:
                    cooking_tm = int(str(cooking_tm).strip()) if cooking_tm not in (None, "") else None
                except Exception:
                    cooking_tm = None
                ingr_qty = parse_listish(row.get(ingr_qty_col)) if ingr_qty_col else []
                image_ln = to_str(row.get(image_link_col)) if image_link_col else ""

                # Insert properties aligned to Recipe schema (CSV-only fields)
                props = {
                    "food_id": rid,
                    "dish_name": title,
                    "dish_type": dish_type,
                    "serving_size": serving_sz,
                    "cooking_time": cooking_tm,
                    "ingredients_with_qty": ingr_qty,
                    "ingredients": ings,
                    "cooking_method_array": dirs,
                    "image_link": image_ln,
                }
                batch.add_object(properties=props, uuid=uuid_recipe(rid))

                processed += 1

                # Progress log theo số dòng
                if processed - last_log_at >= log_every:
                    print_progress(processed, start_ts, max_rows=max_rows, prefix="📈")
                    last_log_at = processed

                if batch.number_errors > 200:
                    print(f"❌ batch.number_errors={batch.number_errors} @ line={file_line}", flush=True)
                    raise RuntimeError("Quá nhiều lỗi khi insert Recipe — dừng lại để kiểm tra")

                # Ghi checkpoint định kỳ
                if checkpoint_file and processed % checkpoint_every == 0:
                    with open(checkpoint_file, "w", encoding="utf-8") as cf:
                        cf.write(f"{file_line},{rid}")
                    print(f"💾 Checkpoint @ line {file_line} (rid={rid})", flush=True)

                # Giới hạn theo max_rows nếu có
                if max_rows is not None and processed >= max_rows:
                    break

    # Kết thúc: in tổng kết
    elapsed = time.time() - start_ts
    rate = processed / elapsed if elapsed > 0 else 0.0
    print(f"✅ Hoàn tất: processed={processed:,}  elapsed={human_sec(elapsed)}  rate={rate:,.1f} rows/s", flush=True)

# --------------------------
# Show & Verify
# --------------------------
def show_recipes(client, limit: int = 10):
    col = client.collections.get("Recipe")
    res = col.query.fetch_objects(limit=limit, include_vector=False)
    print(f"\n📄 Recipe: showing {len(res.objects)} rows")
    for i, obj in enumerate(res.objects, 1):
        p = obj.properties or {}
        name = p.get("dish_name") or ""
        if len(name) > 80: name = name[:80] + "..."
        print(f"\n[{i}] id={p.get('food_id')}  —  {name}")
        print(f"   ingredients: {len(p.get('ingredients') or [])} items")
        print(f"   steps      : {len(p.get('cooking_method_array') or [])} steps")

def verify_recipes(client, sample_size: int = 10):
    col = client.collections.get("Recipe")
    total = col.aggregate.over_all(total_count=True).total_count
    print("\n📊 Collection Statistics:")
    print(f"   Recipe: {total:,} records")
    print(f"\n🍽️ Sample Recipe (first {sample_size}):")
    res = col.query.fetch_objects(limit=sample_size, include_vector=False)
    for i, obj in enumerate(res.objects, 1):
        p = obj.properties or {}
        name = p.get("dish_name") or ""
        if len(name) > 80: name = name[:80] + "..."
        print(f"\n   [{i}] {p.get('food_id')} — {name}")
        print(f"        ingredients={len(p.get('ingredients') or [])} | steps={len(p.get('cooking_method_array') or [])}")

# --------------------------
# CLI
# --------------------------
def main():
    ap = argparse.ArgumentParser(description="Ingest large Recipe CSV (.csv / .csv.gz) into Weaviate (streaming + resume + progress)")
    ap.add_argument("--csv", help="Path tới file recipes.csv hoặc recipes.csv.gz")
    ap.add_argument("--batch-size", type=int, default=400, help="Số object mỗi batch (mặc định 400)")
    ap.add_argument("--start-line", type=int, default=2, help="Bắt đầu từ dòng N (1=header). Mặc định 2 để bỏ header")
    ap.add_argument("--max-rows", type=int, default=None, help="Chỉ ingest tối đa N dòng (mặc định: toàn bộ)")
    ap.add_argument("--checkpoint-file", default=None, help="Ghi tiến độ để resume (vd: recipes.ckpt)")
    ap.add_argument("--checkpoint-every", type=int, default=10000, help="Ghi checkpoint mỗi N dòng")
    ap.add_argument("--log-every", type=int, default=5000, help="In progress log mỗi N dòng (mặc định 5000)")
    ap.add_argument("--show", action="store_true", help="Xem 10 dòng đầu trong Recipe")
    ap.add_argument("--verify", action="store_true", help="Đếm + sample")
    args = ap.parse_args()

    with connect() as client:
        if args.show and not args.csv:
            show_recipes(client, limit=10)
            return

        ran_any = False

        if args.csv:
            ingest_recipes_csv(
                client,
                must_file(args.csv),
                batch_size=args.batch_size,
                start_line=args.start_line,
                max_rows=args.max_rows,
                checkpoint_file=args.checkpoint_file,
                checkpoint_every=args.checkpoint_every,
                log_every=args.log_every,
            )
            ran_any = True

        if args.verify:
            verify_recipes(client, sample_size=10)
            ran_any = True

        if ran_any:
            return

        ap.error("Cần chỉ định --csv <path> (có thể kèm --verify) hoặc dùng --show / --verify")

if __name__ == "__main__":
    main()

# CRUD Pattern cho Tools - Database First, Environment for Navigation

## Nguyên tắc

**Tools phải CRUD trực tiếp với Database (Weaviate), không phải với Environment.**

- ✅ **Database (Weaviate)**: Source of truth cho tất cả business data
- ✅ **Environment**: Chỉ để navigation và metadata sau khi CRUD thành công

## Pattern Chuẩn: Database CRUD → Environment Navigation

### Pattern Đúng:

```python
@tool
async def my_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "read",
    data: dict | None = None,
    **kwargs,
) -> AsyncGenerator[Result | Response | Error, None]:
    """
    CRUD operations for MyCollection.
    
    Pattern:
    1. CRUD với Database (Weaviate) - source of truth
    2. Write vào Environment chỉ để navigation sau khi CRUD thành công
    """
    try:
        client = client_manager.get_client()
        collection = client.collections.get("MyCollection")
        
        # ============================================================
        # STEP 1: CRUD với Database (Weaviate)
        # ============================================================
        
        if action == "create":
            # CREATE: Insert vào database
            collection.data.insert(data)
            yield Response("✅ Created successfully")
            
        elif action == "read":
            # READ: Query từ database
            filter = build_filters_from_where({
                "path": ["id"], "operator": "Equal", "valueString": data.get("id")
            })
            results = collection.query.fetch_objects(filters=filter, limit=1)
            if not results.objects:
                yield Error("Not found")
                return
            data = results.objects[0].properties
            
        elif action == "update":
            # UPDATE: Update trong database
            filter = build_filters_from_where({
                "path": ["id"], "operator": "Equal", "valueString": data.get("id")
            })
            existing = collection.query.fetch_objects(filters=filter, limit=1)
            if not existing.objects:
                yield Error("Not found")
                return
            collection.data.update(uuid=existing.objects[0].uuid, properties=data)
            yield Response("✅ Updated successfully")
            
        elif action == "delete":
            # DELETE: Delete từ database
            filter = build_filters_from_where({
                "path": ["id"], "operator": "Equal", "valueString": data.get("id")
            })
            existing = collection.query.fetch_objects(filters=filter, limit=1)
            if not existing.objects:
                yield Error("Not found")
                return
            collection.data.delete_by_id(existing.objects[0].uuid)
            yield Response("✅ Deleted successfully")
        
        # ============================================================
        # STEP 2: Write vào Environment chỉ để Navigation
        # ============================================================
        # CHỈ write vào environment SAU KHI CRUD với database thành công
        # Environment chỉ để navigation, KHÔNG phải source of truth
        
        yield Result(
            name="result",  # Navigation key
            objects=[data],  # Data để navigation (optional)
            metadata={
                "action": action,
                "timestamp": datetime.now().isoformat(),
                # Metadata để navigation, không phải data chính
            },
            payload_type="generic",
            display=True,
        )
        
    except Exception as e:
        yield Error(f"CRUD operation failed: {str(e)}")
```

## Examples từ Codebase

### ✅ Example 1: profile_crud_tool (ĐÚNG)

```python
@tool
async def profile_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "create",
    profile_data: dict | None = None,
    **kwargs,
):
    # STEP 1: CRUD với Database
    client = client_manager.get_client()
    collection = client.collections.get("UserProfile")
    
    if action == "create":
        # CREATE: Insert vào database
        collection.data.insert(profile_data)
        
    elif action == "update":
        # UPDATE: Update trong database
        existing = collection.query.fetch_objects(...)
        collection.data.update(uuid=existing.objects[0].uuid, properties=profile_data)
        
    elif action == "read":
        # READ: Query từ database
        result = collection.query.fetch_objects(...)
        profile = result.objects[0].properties
    
    # STEP 2: Write vào Environment chỉ để Navigation
    yield Result(
        name="profile",
        objects=[profile_data],  # Navigation data
        metadata={"action": action, "user_id": user_id},  # Navigation metadata
    )
```

### ✅ Example 2: sync_plan_to_weaviate (ĐÚNG)

```python
def sync_plan_to_weaviate(
    plan: Dict[str, Any],
    user_id: str,
    client_manager,
    start_date: str | None = None,
) -> Dict[str, Any]:
    """
    Upsert MealPlan + MealPlanItem records so downstream tools can rely on persisted data.
    """
    client = client_manager.get_client()
    plan_collection = client.collections.get("MealPlan")
    item_collection = client.collections.get("MealPlanItem")
    
    # STEP 1: CRUD với Database
    # Upsert plan
    plan_filter = build_filters_from_where({
        "path": ["plan_id"], "operator": "Equal", "valueString": plan_id
    })
    existing_plan = plan_collection.query.fetch_objects(filters=plan_filter, limit=1)
    if existing_plan.objects:
        plan_collection.data.update(uuid=existing_plan.objects[0].uuid, properties=plan_payload)
    else:
        plan_collection.data.insert(plan_payload)
    
    # Upsert items
    items = _build_plan_items(plan)
    for item in items:
        item_collection.data.insert({"plan_id": plan_id, **item})
    
    # Return updated plan (caller will write to environment if needed)
    return plan
```

### ✅ Example 3: pantry_crud_tool (ĐÚNG)

```python
@tool
async def pantry_crud_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    action: str = "read",
    user_id: str = "",
    pantry_items: List[Dict[str, Any]] | None = None,
    **kwargs,
):
    # STEP 1: CRUD với Database
    client = client_manager.get_client()
    pantry_collection = client.collections.get("Pantry")
    item_collection = client.collections.get("PantryItem")
    
    if action == "read":
        # READ: Query từ database
        pantry_results = pantry_collection.query.fetch_objects(...)
        items_results = item_collection.query.fetch_objects(...)
        items = [obj.properties for obj in items_results.objects]
        
    elif action == "create":
        # CREATE: Insert vào database
        item_collection.data.insert(item_data)
        
    elif action == "update":
        # UPDATE: Update trong database
        existing = item_collection.query.fetch_objects(...)
        item_collection.data.update(uuid=existing.objects[0].uuid, properties=item_data)
        
    elif action == "delete":
        # DELETE: Delete từ database
        existing = item_collection.query.fetch_objects(...)
        item_collection.data.delete_by_id(existing.objects[0].uuid)
    
    # STEP 2: Write vào Environment chỉ để Navigation
    yield Result(
        name="state",
        objects=[state],  # Navigation data
        metadata={"action": action, "user_id": user_id},  # Navigation metadata
    )
```

## Common Mistakes và Cách Tránh

### ❌ Mistake 1: CRUD với Environment thay vì Database

```python
# ❌ SAI: CRUD với environment
tree_data.environment.add_objects("my_tool", "data", objects=[data])
# Data không được lưu vào database!

# ✅ ĐÚNG: CRUD với database trước
collection.data.insert(data)
# Sau đó mới write vào environment để navigation
yield Result(name="data", objects=[data], metadata={"action": "create"})
```

### ❌ Mistake 2: Không CRUD với Database

```python
# ❌ SAI: Chỉ write vào environment
yield Result(name="plan", objects=[plan])
# Plan không được persist!

# ✅ ĐÚNG: CRUD với database trước
plan = sync_plan_to_weaviate(plan, user_id, client_manager)
# Sau đó write vào environment để navigation
yield Result(name="plan", objects=[plan], metadata={"action": "create"})
```

### ❌ Mistake 3: Environment là Source of Truth

```python
# ❌ SAI: Đọc từ environment và coi như source of truth
plan = tree_data.environment.find("plan_day_e2e_tool", "plan")[0]["objects"][0]
# Environment có thể stale!

# ✅ ĐÚNG: Đọc từ database (source of truth)
plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
# Environment chỉ để navigation
```

## CRUD Operations Checklist

Khi implement CRUD tool, đảm bảo:

- [ ] **CREATE**: `collection.data.insert(data)` vào database
- [ ] **READ**: `collection.query.fetch_objects(...)` từ database
- [ ] **UPDATE**: `collection.data.update(uuid=..., properties=...)` trong database
- [ ] **DELETE**: `collection.data.delete_by_id(uuid)` từ database
- [ ] **Environment**: Chỉ write vào environment SAU KHI CRUD thành công
- [ ] **Metadata**: Environment chỉ chứa metadata để navigation, không phải data chính
- [ ] **Error Handling**: Handle database errors properly
- [ ] **Validation**: Validate data trước khi CRUD

## Helper Functions Pattern

Tạo helper functions để standardize CRUD operations:

```python
# MealAgent/tools/utils/crud_helpers.py

def create_in_weaviate(
    collection_name: str,
    data: Dict[str, Any],
    client_manager: ClientManager,
    unique_key: str | None = None,
    unique_value: str | None = None,
) -> Dict[str, Any]:
    """
    Create record in Weaviate.
    If unique_key provided, check for existing record first (upsert).
    """
    client = client_manager.get_client()
    collection = client.collections.get(collection_name)
    
    # Check for existing if unique_key provided
    if unique_key and unique_value:
        filter = build_filters_from_where({
            "path": [unique_key], "operator": "Equal", "valueString": unique_value
        })
        existing = collection.query.fetch_objects(filters=filter, limit=1)
        if existing.objects:
            # Update existing
            collection.data.update(uuid=existing.objects[0].uuid, properties=data)
            return data
    
    # Insert new
    collection.data.insert(data)
    return data

def read_from_weaviate(
    collection_name: str,
    filter_dict: Dict[str, Any],
    client_manager: ClientManager,
    limit: int = 1,
) -> List[Dict[str, Any]]:
    """
    Read records from Weaviate.
    """
    client = client_manager.get_client()
    collection = client.collections.get(collection_name)
    
    filter = build_filters_from_where(filter_dict)
    results = collection.query.fetch_objects(filters=filter, limit=limit)
    
    return [obj.properties for obj in results.objects]

def update_in_weaviate(
    collection_name: str,
    filter_dict: Dict[str, Any],
    data: Dict[str, Any],
    client_manager: ClientManager,
) -> Dict[str, Any] | None:
    """
    Update record in Weaviate.
    """
    client = client_manager.get_client()
    collection = client.collections.get(collection_name)
    
    filter = build_filters_from_where(filter_dict)
    existing = collection.query.fetch_objects(filters=filter, limit=1)
    
    if not existing.objects:
        return None
    
    collection.data.update(uuid=existing.objects[0].uuid, properties=data)
    return data

def delete_from_weaviate(
    collection_name: str,
    filter_dict: Dict[str, Any],
    client_manager: ClientManager,
) -> bool:
    """
    Delete record from Weaviate.
    """
    client = client_manager.get_client()
    collection = client.collections.get(collection_name)
    
    filter = build_filters_from_where(filter_dict)
    existing = collection.query.fetch_objects(filters=filter, limit=1)
    
    if not existing.objects:
        return False
    
    collection.data.delete_by_id(existing.objects[0].uuid)
    return True
```

## Tóm tắt

### ✅ DO:

1. **CRUD trực tiếp với Database (Weaviate)**:
   - `collection.data.insert()` cho CREATE
   - `collection.query.fetch_objects()` cho READ
   - `collection.data.update()` cho UPDATE
   - `collection.data.delete_by_id()` cho DELETE

2. **Write vào Environment sau CRUD thành công**:
   - Chỉ để navigation
   - Chỉ metadata, không phải data chính
   - Optional, không bắt buộc

3. **Use Helper Functions**:
   - Standardize CRUD operations
   - Reduce code duplication
   - Ensure consistency

### ❌ DON'T:

1. **Don't CRUD với Environment**:
   - Environment không phải database
   - Environment không persist data
   - Environment không phải source of truth

2. **Don't Skip Database CRUD**:
   - Luôn CRUD với database trước
   - Không chỉ write vào environment
   - Không assume environment có data

3. **Don't Use Environment as Storage**:
   - Environment chỉ để navigation
   - Business data phải trong database
   - Environment có thể stale

---

**Principle**: Database is source of truth, Environment is for navigation only.



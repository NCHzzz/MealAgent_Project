# Hiểu rõ về Elysia Environment

Dựa trên tài liệu chính thức của Elysia: https://weaviate.github.io/elysia/Advanced/environment/

## 1. Environment là gì?

**Environment** là một **persistent object** được duy trì xuyên suốt tất cả các actions, tools và decisions trong Elysia decision tree. Nó được sử dụng để:

- **Lưu trữ thông tin global** (như retrieved objects)
- **Chia sẻ thông tin** giữa các tools và actions
- **Hỗ trợ LLM agent điều hướng** các tools

## 2. Cấu trúc của Environment

### 2.1. Key Structure

Environment được keyed bởi **2 biến**:

1. **`tool_name`** (str): Tên của tool đã add data vào environment
2. **`name`** (str): Subkey của `tool_name`, một `name` unique liên kết với kết quả từ tool đó

### 2.2. Value Structure

Mỗi entry trong environment là một **list of dictionaries**, mỗi dictionary chứa:

- **`objects`** (list[dict]): Danh sách các objects được retrieve trong lần gọi tool đó
- **`metadata`** (dict): Metadata tương ứng với query/operation đã retrieve data

### 2.3. Ví dụ Cấu trúc

```python
{
    "query": {
        "message_result": [
            {
                "objects": [
                    {"message_id": 1, "message_content": "Hi this is an example message about frogs!"},
                    {"message_id": 2, "message_content": "Hi this is also an example message about reindeer!"},
                ], 
                "metadata": {
                    "collection_name": "example_email_messages_collection",
                    "query_search_term": "animals"
                }
            },
        ]
    },
    "aggregate": {
        "pet_food_result": [
            {
                "objects": [
                    {
                        "average_price": 45.99, 
                        "product_count": 150, 
                    }
                ],
                "metadata": {
                    "collection_name": "pet_food",
                    "group_by": {"field": "animal", "value": "frog"} 
                }
            }
        ]
    }
}
```

**Indexing levels:**
- **Level 1**: `tool_name` (ví dụ: `"query"`, `"aggregate"`)
- **Level 2**: `name` (ví dụ: `"message_result"`, `"pet_food_result"`)
- **Level 3**: List of entries, mỗi entry có `objects` và `metadata`

## 3. Các Methods của Environment

### 3.1. `.add()` và `.add_objects()`

**`.add()`**: Add objects vào environment với automatic assignment

```python
environment.add(objects, metadata={})
```

**`.add_objects()`**: Add objects với explicit `tool_name` và `name`

```python
environment.add_objects(
    tool_name="my_tool",
    name="my_result",
    objects=[{"key": "value"}],
    metadata={"query": "example"}
)
```

**Lưu ý**: Nếu tool trả về `Result` object, Elysia tự động add vào environment với `tool_name` và `name` từ Result.

### 3.2. `.find()`

Retrieve objects từ environment:

```python
results = environment.find(tool_name, name, index=None)
```

- **`tool_name`**: Tên tool
- **`name`**: Name identifier
- **`index`**: Index cụ thể (None = return tất cả)

**Returns**: List of dictionaries với `objects` và `metadata`

**Ví dụ**:
```python
# Get all results from search_and_rank_tool with name "topk"
results = tree_data.environment.find("search_and_rank_tool", "topk")
if results:
    recipes = results[0]["objects"]  # First entry's objects
```

### 3.3. `.replace()`

Replace một item trong environment:

```python
environment.replace(
    tool_name="descriptor", 
    name="animal_description",
    objects=[{"animal": "reindeer", "description": "Has a red nose"}],
    metadata={},
    index=None  # None = replace entire list, or specific index
)
```

### 3.4. `.remove()`

Remove items từ environment:

```python
environment.remove(tool_name, name, index=None)
```

- **`index=None`**: Remove toàn bộ set của `tool_name` và `name`
- **`index=-1`**: Remove entry mới nhất
- **`index=0`**: Remove entry đầu tiên

### 3.5. `.is_empty()`

Check xem environment có rỗng không:

```python
if not tree_data.environment.is_empty():
    # Environment has data
    pass
```

## 4. Hidden Environment

**`environment.hidden_environment`**: Dictionary để lưu data **không show cho LLM**.

**Use cases**:
- Lưu raw retrieval objects với metadata đầy đủ
- Lưu temporary state không cần LLM biết
- Cache data để tránh re-fetch

**Ví dụ**:
```python
# Store in hidden environment (not shown to LLM)
tree_data.environment.hidden_environment["profile"] = fresh_profile
tree_data.environment.hidden_environment["user_id"] = user_id
```

## 5. Environment vs Database

### ✅ Environment DÙNG CHO:

1. **LLM Agent Navigation**:
   - Metadata về tool nào đã chạy
   - Kết quả tạm thời để agent quyết định tool tiếp theo
   - Flags và hints cho agent

2. **System Operations**:
   - Temporary state trong một conversation session
   - Intermediate results giữa các tools
   - Metadata về operations (query terms, filters, etc.)

3. **Tool Coordination**:
   - Chia sẻ kết quả giữa các tools trong cùng session
   - Tracking tool execution history
   - Context cho downstream tools

### ❌ Environment KHÔNG DÙNG CHO:

1. **Primary Data Storage**:
   - ❌ Recipes, Plans, Profiles, Pantry
   - ❌ Bất kỳ data nào cần persistence
   - ❌ Source of truth cho business data

2. **Long-term Storage**:
   - Environment chỉ tồn tại trong một conversation session
   - Không persist giữa các sessions
   - Không có backup/recovery

3. **Data Integrity**:
   - Environment có thể stale
   - Không có versioning
   - Không có transaction support

### ✅ Database (Weaviate) DÙNG CHO:

1. **Source of Truth**:
   - ✅ Recipes, Plans, Profiles, Pantry
   - ✅ Tất cả business data
   - ✅ Data cần persistence và consistency

2. **Data Freshness**:
   - ✅ Luôn có data mới nhất
   - ✅ Single source of truth
   - ✅ Consistent across sessions

## 6. Pattern Đúng cho Tools

### Pattern 1: Read from Database First

```python
@tool
async def my_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    plan_id: str | None = None,
    user_id: str | None = None,
    **kwargs,
):
    # 1. Try database first (source of truth)
    if plan_id:
        plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
    elif user_id:
        plan = load_latest_plan_from_weaviate(user_id, client_manager)
    
    # 2. Fallback to environment cache (only as last resort)
    if not plan:
        plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
        if plan_results and plan_results[0]["objects"]:
            plan = plan_results[0]["objects"][0]
            yield Response("⚠️ Using cached plan (please provide plan_id for database access)")
    
    if not plan:
        yield Error("No plan found. Please provide plan_id or user_id.")
        return
    
    # 3. Process and return results
    yield Result(name="result", objects=[plan], metadata={"source": "database"})
```

### Pattern 2: Use Environment for Navigation Only

```python
@tool
async def my_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    **kwargs,
):
    # Check if previous tool has run (navigation)
    previous_results = tree_data.environment.find("previous_tool", "result")
    if previous_results:
        # Use metadata for navigation, not data itself
        metadata = previous_results[0].get("metadata", {})
        query_term = metadata.get("query_term", "")
    
    # Always fetch fresh data from database
    client = client_manager.get_client()
    collection = client.collections.get("MyCollection")
    # ... query from database ...
    
    # Store result in environment for next tool (navigation)
    yield Result(
        name="result",
        objects=[fresh_data],
        metadata={"query_term": query_term, "timestamp": datetime.now()}
    )
```

### Pattern 3: Use Hidden Environment for Caching

```python
@tool
async def my_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    user_id: str,
    **kwargs,
):
    # Check hidden environment cache (not shown to LLM)
    hidden = tree_data.environment.hidden_environment
    if "profile" in hidden and hidden["profile"].get("user_id") == user_id:
        profile = hidden["profile"]
    else:
        # Fetch from database
        client = client_manager.get_client()
        collection = client.collections.get("UserProfile")
        # ... query ...
        profile = result.properties
        # Cache in hidden environment
        hidden["profile"] = profile
    
    # Use profile for processing
    # ...
```

## 7. Common Mistakes và Cách Tránh

### ❌ Mistake 1: Environment as Primary Source

```python
# ❌ SAI: Đọc từ environment trước
plan_results = tree_data.environment.find("plan_day_e2e_tool", "plan")
plan = plan_results[0]["objects"][0] if plan_results else None

# ✅ ĐÚNG: Đọc từ database trước
if plan_id:
    plan = load_plan_from_weaviate(plan_id, client_manager, user_id)
elif user_id:
    plan = load_latest_plan_from_weaviate(user_id, client_manager)
# Fallback to environment only if no plan_id/user_id
```

### ❌ Mistake 2: Storing Business Data in Environment

```python
# ❌ SAI: Store recipes in environment
tree_data.environment.add_objects(
    "my_tool",
    "recipes",
    objects=recipes  # Business data should be in database
)

# ✅ ĐÚNG: Store metadata/navigation info
tree_data.environment.add_objects(
    "my_tool",
    "search_metadata",
    objects=[{"query": "Vietnamese recipes", "count": len(recipes)}],
    metadata={"timestamp": datetime.now()}
)
# Recipes themselves stay in database
```

### ❌ Mistake 3: Not Refreshing from Database

```python
# ❌ SAI: Trust environment data without refresh
profile = tree_data.environment.find("profile_crud_tool", "profile")[0]["objects"][0]

# ✅ ĐÚNG: Always refresh from database
profile_results = tree_data.environment.find("profile_crud_tool", "profile")
if profile_results:
    cached_profile = profile_results[0]["objects"][0]
    user_id = cached_profile.get("user_id")
    # Hard refresh from database
    client = client_manager.get_client()
    collection = client.collections.get("UserProfile")
    fresh_profile = collection.query.fetch_objects(...)
    profile = fresh_profile.objects[0].properties
```

## 8. Best Practices

### ✅ DO:

1. **Use Environment for Navigation**:
   - Tool execution history
   - Metadata about operations
   - Temporary state for agent decisions

2. **Always Read from Database**:
   - Business data (recipes, plans, profiles)
   - Source of truth data
   - Data that needs consistency

3. **Use Hidden Environment for Caching**:
   - Cache expensive operations
   - Store raw objects with full metadata
   - Avoid re-fetching within same session

4. **Fallback Pattern**:
   - Try database first
   - Fallback to environment only if no identifiers available
   - Warn user when using cached data

### ❌ DON'T:

1. **Don't Use Environment as Primary Storage**:
   - Don't store business data
   - Don't rely on environment for data freshness
   - Don't use environment as source of truth

2. **Don't Skip Database Refresh**:
   - Don't trust cached data without refresh
   - Don't assume environment has latest data
   - Don't use environment data for critical operations

3. **Don't Mix Concerns**:
   - Don't store navigation data in database
   - Don't store business data in environment
   - Keep concerns separated

## 9. Tóm tắt

### Environment là gì?
- **Persistent object** trong một conversation session
- **Keyed by** `tool_name` và `name`
- **Contains** `objects` và `metadata` từ tools

### Environment dùng để làm gì?
- ✅ **LLM Agent Navigation**: Metadata để agent điều hướng
- ✅ **System Operations**: Temporary state, flags, hints
- ✅ **Tool Coordination**: Chia sẻ kết quả giữa tools
- ❌ **NOT** for primary data storage

### Database (Weaviate) dùng để làm gì?
- ✅ **Source of Truth**: Business data (recipes, plans, profiles)
- ✅ **Data Freshness**: Luôn có data mới nhất
- ✅ **Persistence**: Data tồn tại giữa các sessions
- ✅ **Consistency**: Single source of truth

### Pattern Đúng:
1. **Read from Database first** (source of truth)
2. **Use Environment for navigation** (metadata, flags)
3. **Fallback to Environment** only if no identifiers available
4. **Warn user** when using cached data

---

**References**:
- [Elysia Environment Documentation](https://weaviate.github.io/elysia/Advanced/environment/)
- [Elysia Creating Tools](https://weaviate.github.io/elysia/creating_tools/)
- [Elysia API Reference](https://weaviate.github.io/elysia/API/)



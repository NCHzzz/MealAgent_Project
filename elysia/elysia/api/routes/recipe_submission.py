"""
Recipe Submission API routes.

User flow:
1. POST /recipe/submit - Submit recipe (status=pending)
2. GET /recipe/my-submissions - View own submissions

Admin flow:
1. GET /recipe/admin/pending - List pending submissions
2. POST /recipe/admin/{submission_id}/approve - Approve and copy to Recipe collection
3. POST /recipe/admin/{submission_id}/reject - Reject with reason
"""

from fastapi import APIRouter, Depends, Body, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
import uuid

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from weaviate.classes.query import Filter

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class MacrosInput(BaseModel):
    kcal: Optional[float] = None
    protein_g: Optional[float] = None
    fat_g: Optional[float] = None
    carb_g: Optional[float] = None


class RecipeSubmitInput(BaseModel):
    dish_name: str = Field(..., min_length=1, max_length=200)
    dish_type: Optional[str] = None
    serving_size: Optional[int] = Field(default=1, ge=1)
    cooking_time: Optional[int] = Field(default=None, ge=0)
    ingredients_with_qty: Optional[List[str]] = None
    ingredients: Optional[List[str]] = None
    cooking_method_array: Optional[List[str]] = None
    image_link: Optional[str] = None
    diet_type: Optional[List[str]] = None
    allergens: Optional[List[str]] = None
    devices: Optional[List[str]] = None
    macros_per_serving: Optional[MacrosInput] = None


class RejectInput(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


# =============================================================================
# USER ENDPOINTS
# =============================================================================

@router.post("/submit")
async def submit_recipe(
    user_id: str = Query(..., description="User ID submitting the recipe"),
    data: RecipeSubmitInput = Body(...),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Submit a new recipe for admin approval.
    
    The recipe will be stored with status='pending' until an admin reviews it.
    """
    logger.info(f"Recipe submission request from user: {user_id}")
    
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            # Generate unique submission ID
            submission_id = f"sub_{uuid.uuid4().hex[:12]}"
            
            # Build properties
            properties = {
                "submission_id": submission_id,
                "submitted_by": user_id,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
                **data.model_dump(exclude_none=True),
            }
            
            # Handle nested macros object
            if data.macros_per_serving:
                properties["macros_per_serving"] = data.macros_per_serving.model_dump(exclude_none=True)
            
            weaviate_uuid = await collection.data.insert(properties=properties)
            
            logger.info(f"Recipe submitted: {submission_id} by user {user_id}")
            
            return JSONResponse(
                content={
                    "submission_id": submission_id,
                    "uuid": str(weaviate_uuid),
                    "status": "pending",
                    "message": f"Công thức '{data.dish_name}' đã được gửi và đang chờ duyệt",
                    "error": "",
                },
                status_code=201,
            )
    except Exception as e:
        logger.exception(f"Error submitting recipe: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@router.get("/my-submissions")
async def get_my_submissions(
    user_id: str = Query(..., description="User ID"),
    status: Optional[str] = Query(None, description="Filter by status: pending, approved, rejected"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Get user's own recipe submissions.
    
    Returns all submissions made by the user, optionally filtered by status.
    """
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            # Build filter
            filter_obj = Filter.by_property("submitted_by").equal(user_id)
            if status:
                filter_obj = filter_obj & Filter.by_property("status").equal(status)
            
            results = await collection.query.fetch_objects(
                filters=filter_obj,
                limit=limit,
                offset=offset,
            )
            
            submissions = []
            for obj in results.objects:
                sub = dict(obj.properties)
                sub["uuid"] = str(obj.uuid)
                # Convert datetime objects to ISO strings
                for key in ["submitted_at", "reviewed_at"]:
                    if sub.get(key) and hasattr(sub[key], "isoformat"):
                        sub[key] = sub[key].isoformat()
                submissions.append(sub)
            
            return JSONResponse(
                content={
                    "submissions": submissions,
                    "count": len(submissions),
                    "error": "",
                },
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error fetching submissions: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@router.get("/submission/{submission_id}")
async def get_submission_detail(
    submission_id: str,
    user_id: str = Query(..., description="User ID"),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Get details of a specific submission.
    
    Users can only view their own submissions.
    """
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            # Filter by submission_id and owner
            filter_obj = (
                Filter.by_property("submission_id").equal(submission_id) &
                Filter.by_property("submitted_by").equal(user_id)
            )
            
            results = await collection.query.fetch_objects(filters=filter_obj, limit=1)
            
            if not results.objects:
                return JSONResponse(
                    content={"error": f"Không tìm thấy submission '{submission_id}'"},
                    status_code=404,
                )
            
            sub = dict(results.objects[0].properties)
            sub["uuid"] = str(results.objects[0].uuid)
            
            # Convert datetime objects
            for key in ["submitted_at", "reviewed_at"]:
                if sub.get(key) and hasattr(sub[key], "isoformat"):
                    sub[key] = sub[key].isoformat()
            
            return JSONResponse(
                content={"submission": sub, "error": ""},
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error fetching submission detail: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


# =============================================================================
# ADMIN ENDPOINTS
# =============================================================================

@router.get("/admin/pending")
async def get_pending_submissions(
    user_id: str = Query(..., description="Admin user ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    [ADMIN] Get all pending recipe submissions.
    
    Lists all submissions with status='pending' for admin review.
    """
    try:
        # TODO: Add admin role verification
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            filter_obj = Filter.by_property("status").equal("pending")
            results = await collection.query.fetch_objects(
                filters=filter_obj,
                limit=limit,
                offset=offset,
            )
            
            submissions = []
            for obj in results.objects:
                sub = dict(obj.properties)
                sub["uuid"] = str(obj.uuid)
                # Convert datetime objects
                for key in ["submitted_at", "reviewed_at"]:
                    if sub.get(key) and hasattr(sub[key], "isoformat"):
                        sub[key] = sub[key].isoformat()
                submissions.append(sub)
            
            logger.info(f"Admin {user_id} fetched {len(submissions)} pending submissions")
            
            return JSONResponse(
                content={
                    "pending": submissions,
                    "count": len(submissions),
                    "error": "",
                },
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error fetching pending submissions: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@router.get("/admin/all")
async def get_all_submissions(
    user_id: str = Query(..., description="Admin user ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    [ADMIN] Get all recipe submissions with optional status filter.
    """
    try:
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            filter_obj = None
            if status:
                filter_obj = Filter.by_property("status").equal(status)
            
            if filter_obj:
                results = await collection.query.fetch_objects(
                    filters=filter_obj,
                    limit=limit,
                    offset=offset,
                )
            else:
                results = await collection.query.fetch_objects(
                    limit=limit,
                    offset=offset,
                )
            
            submissions = []
            for obj in results.objects:
                sub = dict(obj.properties)
                sub["uuid"] = str(obj.uuid)
                for key in ["submitted_at", "reviewed_at"]:
                    if sub.get(key) and hasattr(sub[key], "isoformat"):
                        sub[key] = sub[key].isoformat()
                submissions.append(sub)
            
            return JSONResponse(
                content={
                    "submissions": submissions,
                    "count": len(submissions),
                    "error": "",
                },
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error fetching all submissions: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@router.post("/admin/{submission_id}/approve")
async def approve_submission(
    submission_id: str,
    user_id: str = Query(..., description="Admin user ID"),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    [ADMIN] Approve a recipe submission.
    
    Copies the recipe data to the main Recipe collection and updates
    the submission status to 'approved'.
    """
    try:
        # TODO: Add admin role verification
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            submission_col = client.collections.get("RecipeSubmission")
            recipe_col = client.collections.get("Recipe")
            
            # Find submission
            filter_obj = Filter.by_property("submission_id").equal(submission_id)
            results = await submission_col.query.fetch_objects(filters=filter_obj, limit=1)
            
            if not results.objects:
                return JSONResponse(
                    content={"error": f"Không tìm thấy submission '{submission_id}'"},
                    status_code=404,
                )
            
            submission = results.objects[0]
            props = dict(submission.properties)
            
            if props.get("status") != "pending":
                return JSONResponse(
                    content={"error": f"Submission đã được xử lý: {props.get('status')}"},
                    status_code=400,
                )
            
            # Generate food_id for Recipe collection - get next available integer
            try:
                # Get max food_id from existing recipes
                all_recipes = await recipe_col.query.fetch_objects(limit=10000)
                max_id = 0
                for recipe in all_recipes.objects:
                    try:
                        current_id = int(recipe.properties.get("food_id", 0))
                        if current_id > max_id:
                            max_id = current_id
                    except (ValueError, TypeError):
                        pass
                food_id = str(max_id + 1)
            except Exception:
                # Fallback to timestamp-based ID if query fails
                food_id = str(int(datetime.now(timezone.utc).timestamp()))
            
            # Build recipe properties (exclude submission metadata)
            recipe_props = {
                "food_id": food_id,
                "dish_name": props.get("dish_name"),
                "dish_type": props.get("dish_type"),
                "serving_size": props.get("serving_size"),
                "cooking_time": props.get("cooking_time"),
                "ingredients_with_qty": props.get("ingredients_with_qty"),
                "ingredients": props.get("ingredients"),
                "cooking_method_array": props.get("cooking_method_array"),
                "image_link": props.get("image_link"),
                "diet_type": props.get("diet_type"),
                "allergens": props.get("allergens"),
                "devices": props.get("devices"),
                "macros_per_serving": props.get("macros_per_serving"),
            }
            
            # Remove None values
            recipe_props = {k: v for k, v in recipe_props.items() if v is not None}
            
            # Insert into Recipe collection
            await recipe_col.data.insert(properties=recipe_props)
            
            # Update submission status
            await submission_col.data.update(
                uuid=submission.uuid,
                properties={
                    "status": "approved",
                    "reviewed_by": user_id,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            
            logger.info(f"Recipe approved: {submission_id} -> {food_id} by admin {user_id}")
            
            return JSONResponse(
                content={
                    "message": f"Công thức '{props.get('dish_name')}' đã được duyệt",
                    "food_id": food_id,
                    "submission_id": submission_id,
                    "error": "",
                },
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error approving submission: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )


@router.post("/admin/{submission_id}/reject")
async def reject_submission(
    submission_id: str,
    user_id: str = Query(..., description="Admin user ID"),
    data: RejectInput = Body(...),
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    [ADMIN] Reject a recipe submission.
    
    Updates the submission status to 'rejected' with a rejection reason.
    """
    try:
        # TODO: Add admin role verification
        user_local = await user_manager.get_user_local(user_id)
        client_manager = user_local["client_manager"]
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("RecipeSubmission")
            
            filter_obj = Filter.by_property("submission_id").equal(submission_id)
            results = await collection.query.fetch_objects(filters=filter_obj, limit=1)
            
            if not results.objects:
                return JSONResponse(
                    content={"error": f"Không tìm thấy submission '{submission_id}'"},
                    status_code=404,
                )
            
            submission = results.objects[0]
            props = dict(submission.properties)
            
            if props.get("status") != "pending":
                return JSONResponse(
                    content={"error": f"Submission đã được xử lý: {props.get('status')}"},
                    status_code=400,
                )
            
            # Update submission status to rejected
            await collection.data.update(
                uuid=submission.uuid,
                properties={
                    "status": "rejected",
                    "reviewed_by": user_id,
                    "reviewed_at": datetime.now(timezone.utc).isoformat(),
                    "rejection_reason": data.reason,
                },
            )
            
            logger.info(f"Recipe rejected: {submission_id} by admin {user_id}, reason: {data.reason}")
            
            return JSONResponse(
                content={
                    "message": f"Công thức đã bị từ chối: {data.reason}",
                    "submission_id": submission_id,
                    "error": "",
                },
                status_code=200,
            )
    except Exception as e:
        logger.exception(f"Error rejecting submission: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500,
        )

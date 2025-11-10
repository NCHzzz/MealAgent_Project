"""
REST and WebSocket endpoints for meal logging functionality.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.api.utils.websocket import help_websocket
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager

# Import MealAgent tools and workflows
from elysia.MealAgent.tree.meal_tree import process_meal_logging_workflow
from elysia.MealAgent.tree.config import MEAL_AGENT_TOOLS
from elysia.MealAgent.tools.meal_logging.meal_history import meal_history_tool

router = APIRouter()


# Request/Response Models
class MealLogRequest(BaseModel):
    """Request model for logging a meal."""
    user_id: str
    meal_description: str


class MealLogResponse(BaseModel):
    """Response model for meal logging."""
    log_id: str
    calculated_macros: dict
    remaining_targets: dict
    consumed_today: dict
    consumed_this_meal: dict


class MealHistoryResponse(BaseModel):
    """Response model for meal history."""
    user_id: str
    logs: list
    daily_totals: dict
    total_logs: int
    date_range: Optional[dict] = None


class ConsumedTodayResponse(BaseModel):
    """Response model for today's consumed nutrition."""
    user_id: str
    consumed_today: dict
    remaining_targets: dict
    date: str


# REST Endpoints

@router.post("/api/v1/meal/meals/log", response_model=MealLogResponse, tags=["meals"])
async def log_meal(
    request: MealLogRequest,
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Log a consumed meal via natural language description.
    
    This endpoint parses the meal description, calculates nutrition,
    and updates the user's profile with consumed nutrition.
    """
    logger.info(f"Meal log request for user {request.user_id}")
    
    try:
        user = await user_manager.get_user_local(user_id=request.user_id)
        client_manager: ClientManager = user["client_manager"]
        
        # Get base_lm from tree manager settings
        tree_manager = user["tree_manager"]
        base_lm = tree_manager.settings.base_lm
        
        # Create tree_data for workflow
        tree_data = TreeData()
        
        # Execute meal logging workflow
        result_data = {}
        async for result in process_meal_logging_workflow(
            tree_data=tree_data,
            client_manager=client_manager,
            base_lm=base_lm,
            user_id=request.user_id,
            meal_description=request.meal_description,
        ):
            if isinstance(result, Error):
                logger.error(f"Meal logging error: {result.message}")
                raise HTTPException(status_code=400, detail=result.message)
            
            if isinstance(result, Result) and result.name == "updated_profile":
                result_data = result.objects[0] if result.objects else {}
        
        if not result_data:
            raise HTTPException(status_code=500, detail="Failed to log meal")
        
        return MealLogResponse(
            log_id=result_data.get("log_entry", {}).get("log_id", ""),
            calculated_macros=result_data.get("consumed_this_meal", {}),
            remaining_targets=result_data.get("remaining_targets", {}),
            consumed_today=result_data.get("consumed_today", {}),
            consumed_this_meal=result_data.get("consumed_this_meal", {}),
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error logging meal for user {request.user_id}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/meal/meals/history/{user_id}", response_model=MealHistoryResponse, tags=["meals"])
async def get_meal_history(
    user_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Get meal log history for a user with optional date filtering.
    """
    logger.info(f"Meal history request for user {user_id}")
    
    try:
        user = await user_manager.get_user_local(user_id=user_id)
        client_manager: ClientManager = user["client_manager"]
        
        # Create tree_data for tool
        tree_data = TreeData()
        
        # Execute meal_history_tool
        history_data = {}
        async for result in meal_history_tool(
            tree_data=tree_data,
            client_manager=client_manager,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        ):
            if isinstance(result, Error):
                logger.error(f"Meal history error: {result.message}")
                raise HTTPException(status_code=400, detail=result.message)
            
            if isinstance(result, Result) and result.name == "history":
                history_data = result.objects[0] if result.objects else {}
        
        if not history_data:
            raise HTTPException(status_code=404, detail="No meal history found")
        
        return MealHistoryResponse(**history_data)
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving meal history for user {user_id}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/meal/meals/consumed-today/{user_id}", response_model=ConsumedTodayResponse, tags=["meals"])
async def get_consumed_today(
    user_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    Get today's consumed nutrition and remaining targets for a user.
    """
    logger.info(f"Consumed today request for user {user_id}")
    
    try:
        user = await user_manager.get_user_local(user_id=user_id)
        client_manager: ClientManager = user["client_manager"]
        
        with client_manager.connect_to_client() as client:
            profile_collection = client.collections.get("UserProfile")
            log_collection = client.collections.get("MealLogEntry")
            
            # Read profile
            profile_results = profile_collection.query.fetch_objects(
                where={"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                limit=1,
            )
            
            if not profile_results.objects:
                raise HTTPException(status_code=404, detail=f"Profile not found for user {user_id}")
            
            profile = profile_results.objects[0].properties
            
            # Get today's consumed nutrition
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            today_logs = log_collection.query.fetch_objects(
                where={
                    "operator": "And",
                    "operands": [
                        {"path": ["user_id"], "operator": "Equal", "valueString": user_id},
                        {"path": ["logged_at"], "operator": "GreaterThanEqual", "valueDate": today_start.isoformat()},
                        {"path": ["logged_at"], "operator": "LessThan", "valueDate": today_end.isoformat()},
                    ],
                },
            )
            
            # Aggregate today's consumed
            today_consumed = {"kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carb_g": 0.0}
            for log_obj in today_logs.objects:
                log_macros_str = log_obj.properties.get("calculated_macros", "{}")
                if isinstance(log_macros_str, str):
                    try:
                        log_macros = json.loads(log_macros_str)
                    except json.JSONDecodeError:
                        log_macros = {}
                else:
                    log_macros = log_macros_str
                
                if isinstance(log_macros, dict):
                    today_consumed["kcal"] += float(log_macros.get("kcal", 0.0))
                    today_consumed["protein_g"] += float(log_macros.get("protein_g", 0.0))
                    today_consumed["fat_g"] += float(log_macros.get("fat_g", 0.0))
                    today_consumed["carb_g"] += float(log_macros.get("carb_g", 0.0))
            
            # Calculate remaining targets
            target_macros = {
                "kcal": float(profile.get("tdee_kcal", 2000)),
                "protein_g": float(profile.get("protein_g", 150)),
                "fat_g": float(profile.get("fat_g", 67)),
                "carb_g": float(profile.get("carb_g", 200)),
            }
            
            remaining_targets = {
                "kcal": max(0.0, target_macros["kcal"] - today_consumed["kcal"]),
                "protein_g": max(0.0, target_macros["protein_g"] - today_consumed["protein_g"]),
                "fat_g": max(0.0, target_macros["fat_g"] - today_consumed["fat_g"]),
                "carb_g": max(0.0, target_macros["carb_g"] - today_consumed["carb_g"]),
            }
            
            return ConsumedTodayResponse(
                user_id=user_id,
                consumed_today=today_consumed,
                remaining_targets=remaining_targets,
                date=today_start.date().isoformat(),
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error retrieving consumed today for user {user_id}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# WebSocket Endpoint

async def process_meal_log(
    data: dict, websocket: WebSocket, user_manager: UserManager, path_user_id: str = None
):
    """
    Process meal logging via WebSocket with streaming results.
    """
    logger.debug(f"/meals/log WebSocket request received")
    
    # Get user_id from path parameter or data
    user_id = path_user_id or data.get("user_id")
    meal_description = data.get("meal_description")
    
    logger.debug(f"User ID: {user_id}")
    logger.debug(f"Meal description: {meal_description}")
    
    if not user_id or not meal_description:
        await websocket.send_json({
            "type": "error",
            "data": {
                "error": "user_id and meal_description are required",
                "recoverable": False,
            },
        })
        return
    
    try:
        user = await user_manager.get_user_local(user_id=user_id)
        client_manager: ClientManager = user["client_manager"]
        
        # Get base_lm from tree manager settings
        tree_manager = user["tree_manager"]
        base_lm = tree_manager.settings.base_lm
        
        # Create tree_data for workflow
        tree_data = TreeData()
        
        # Execute meal logging workflow with streaming
        async for result in process_meal_logging_workflow(
            tree_data=tree_data,
            client_manager=client_manager,
            base_lm=base_lm,
            user_id=user_id,
            meal_description=meal_description,
        ):
            try:
                if isinstance(result, str):
                    # Text message
                    await websocket.send_json({
                        "type": "text",
                        "data": {
                            "message": result,
                        },
                    })
                elif isinstance(result, Result):
                    # Result object
                    await websocket.send_json({
                        "type": "result",
                        "data": {
                            "tool_name": result.name if hasattr(result, 'name') else "unknown",
                            "name": result.name,
                            "objects": result.objects,
                            "metadata": result.metadata,
                        },
                    })
                elif isinstance(result, Error):
                    # Error object
                    await websocket.send_json({
                        "type": "error",
                        "data": {
                            "error": result.message,
                            "recoverable": True,
                        },
                    })
            except WebSocketDisconnect:
                logger.info("Client disconnected during meal logging")
                break
            
            await asyncio.sleep(0.001)  # Small delay to prevent overwhelming the client
        
        logger.debug("(process_meal_log) FINISHED!")
    
    except Exception as e:
        logger.exception(f"Error in process_meal_log for user {user_id}")
        try:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "error": str(e),
                    "recoverable": False,
                },
            })
        except WebSocketDisconnect:
            logger.info("Client disconnected during error handling")


@router.websocket("/ws/meals/log/{user_id}")
async def meal_log_websocket(
    websocket: WebSocket,
    user_id: str,
    user_manager: UserManager = Depends(get_user_manager),
):
    """
    WebSocket endpoint for real-time meal logging with streaming.
    
    Client sends:
    {
        "meal_description": "Tôi vừa ăn salad gà"
    }
    
    Note: user_id is taken from the path parameter.
    
    Server streams:
    - Text messages (parsing progress, calculation status)
    - Result objects (parsed meal, calculated nutrition, updated profile)
    - Error objects (if any errors occur)
    """
    await help_websocket(
        websocket,
        lambda data, ws: process_meal_log(data, ws, user_manager, path_user_id=user_id),
    )


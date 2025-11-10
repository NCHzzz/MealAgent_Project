"""
Cooking & Explanation API routes.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket
from pydantic import BaseModel

from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.api.utils.websocket import help_websocket
from elysia.tree.objects import TreeData
from elysia.objects import Result, Error
from elysia.util.client import ClientManager

from elysia.MealAgent.tree.config import MEAL_AGENT_TOOLS
from elysia.MealAgent.tools.cook_mode.cook_mode import cook_mode_tool
from elysia.MealAgent.tools.explain.explain import explain_tool


router = APIRouter()


class CookRequest(BaseModel):
    """Request for cooking guidance."""
    user_id: str
    food_id: Optional[str] = None


class CookResponse(BaseModel):
    """Response with steps (non-streaming)."""
    food_id: Optional[str]
    dish_name: Optional[str]
    steps: list


@router.post("/api/v1/meal/cook", response_model=CookResponse, tags=["meals"])  # Non-streaming convenience
async def cook_once(request: CookRequest, user_manager: UserManager = Depends(get_user_manager)):
    logger.info(f"Cook request for user {request.user_id} food_id={request.food_id}")
    try:
        user = await user_manager.get_user_local(user_id=request.user_id)
        client_manager: ClientManager = user["client_manager"]
        tree_data = TreeData()

        last_steps = None
        async for item in cook_mode_tool(
            tree_data=tree_data,
            client_manager=client_manager,
            food_id=request.food_id,
        ):
            if isinstance(item, Error):
                raise HTTPException(status_code=400, detail=item.message)
            if isinstance(item, Result) and item.name == "steps":
                last_steps = item.objects[0]

        if not last_steps:
            raise HTTPException(status_code=404, detail="No steps generated")

        return CookResponse(
            food_id=last_steps.get("food_id"),
            dish_name=last_steps.get("dish_name"),
            steps=last_steps.get("steps", []),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("CookOnce failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.websocket("/ws/meal/cook/{user_id}")
async def cook_ws(websocket: WebSocket, user_id: str, user_manager: UserManager = Depends(get_user_manager)):
    async def handler(data: dict, ws: WebSocket):
        food_id = data.get("food_id")
        try:
            user = await user_manager.get_user_local(user_id=user_id)
            client_manager: ClientManager = user["client_manager"]
            tree_data = TreeData()

            async for item in cook_mode_tool(
                tree_data=tree_data,
                client_manager=client_manager,
                food_id=food_id,
            ):
                if isinstance(item, str):
                    await ws.send_json({"type": "text", "data": {"message": item}})
                elif isinstance(item, Result):
                    await ws.send_json({"type": "result", "data": {"name": item.name, "objects": item.objects, "metadata": item.metadata}})
                elif isinstance(item, Error):
                    await ws.send_json({"type": "error", "data": {"error": item.message}})
        except Exception as e:
            await ws.send_json({"type": "error", "data": {"error": str(e)}})

    await help_websocket(websocket, handler)


class ExplainRequest(BaseModel):
    """Request for explanation generation."""
    user_id: str


class ExplainResponse(BaseModel):
    text: str


@router.post("/api/v1/meal/explain", response_model=ExplainResponse, tags=["meals"])  # Non-streaming
async def explain_once(request: ExplainRequest, user_manager: UserManager = Depends(get_user_manager)):
    logger.info(f"Explain request for user {request.user_id}")
    try:
        user = await user_manager.get_user_local(user_id=request.user_id)
        client_manager: ClientManager = user["client_manager"]
        tree_manager = user["tree_manager"]
        base_lm = tree_manager.settings.base_lm
        tree_data = TreeData()

        text = None
        async for item in explain_tool(tree_data=tree_data, client_manager=client_manager, base_lm=base_lm):
            if isinstance(item, Error):
                raise HTTPException(status_code=400, detail=item.message)
            if isinstance(item, Result) and item.name == "explanation":
                obj = item.objects[0] if item.objects else {}
                text = obj.get("text")
            elif isinstance(item, str):
                # Last textual message is the explanation
                text = item

        if not text:
            raise HTTPException(status_code=404, detail="No explanation generated")

        return ExplainResponse(text=text)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ExplainOnce failed")
        raise HTTPException(status_code=500, detail=str(e))


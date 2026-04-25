import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, status
from starlette.websockets import WebSocketDisconnect

from elysia.tree.tree import Tree
from elysia.api.core.log import logger
from elysia.api.dependencies.common import get_user_manager
from elysia.api.services.user import UserManager
from elysia.api.utils.websocket import help_websocket
from elysia.api.utils.ner import named_entity_recognition
from elysia.util.collection import retrieve_all_collection_names
from elysia.api.utils.default_payloads import error_payload
from elysia.api.routes.auth import _validate_token

router = APIRouter()


def format_ner_response(text: str, user_id: str, conversation_id: str, query_id: str):
    response = named_entity_recognition(text)
    return {
        "type": "ner",
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "conversation_id": conversation_id,
        "query_id": query_id,
        "payload": response,
    }


async def format_title_response(
    tree: Tree, user_id: str, conversation_id: str, query_id: str
):

    try:
        title = await tree.create_conversation_title_async()
        return {
            "type": "title",
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query_id": query_id,
            "payload": {
                "title": title,
                "error": "",
            },
        }
    except Exception as e:
        logger.exception(f"Error in format_title_response")
        return {
            "type": "title",
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "conversation_id": conversation_id,
            "query_id": query_id,
            "payload": {
                "title": "",
                "error": str(e),
            },
        }


async def process(data: dict, websocket: WebSocket, user_manager: UserManager, authenticated_user_id: str | None = None):
    logger.debug(f"/query API request received")
    request_user_id = data.get("user_id")
    user_id = authenticated_user_id or request_user_id
    if authenticated_user_id and request_user_id and request_user_id != authenticated_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated user does not match query payload user",
        )
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authenticated user")
    data["user_id"] = user_id

    logger.debug(f"User ID: {user_id}")
    logger.debug(f"Conversation ID: {data['conversation_id']}")
    logger.debug(f"Query: {data['query']}")
    logger.debug(f"Query ID: {data['query_id']}")
    logger.debug(f"Training route: {data['route']}")
    logger.debug(f"Training mimick model: {data['mimick']}")
    logger.debug(f"Collection names: {data['collection_names']}")

    user = await user_manager.get_user_local(user_id=user_id)

    try:
        # optional arguments
        if "route" in data:
            route = data["route"]
        else:
            route = ""

        # send ner response in advance
        await websocket.send_json(
            format_ner_response(
                text=data["query"],
                user_id=user_id,
                conversation_id=data["conversation_id"],
                query_id=data["query_id"],
            )
        )

        async for yielded_result in user_manager.process_tree(
            user_id=user_id,
            conversation_id=data["conversation_id"],
            query=data["query"],
            query_id=data["query_id"],
            training_route=route,
            collection_names=data["collection_names"],
        ):
            if asyncio.iscoroutine(yielded_result):
                yielded_result = await yielded_result
            try:
                if (
                    yielded_result is not None
                    and "type" in yielded_result
                    and yielded_result["type"] != "training_update"
                    and yielded_result["type"] != "timer"
                    and yielded_result["type"] != "completed"
                ):
                    await websocket.send_json(yielded_result)

                # before the completed, send title of conversation
                elif (
                    yielded_result is not None
                    and "type" in yielded_result
                    and yielded_result["type"] == "completed"
                ):
                    tree: Tree = await user_manager.get_tree(
                        user_id=user_id,
                        conversation_id=data["conversation_id"],
                    )

                    # only send if it's the first prompt
                    if tree.tree_index == 0:
                        await websocket.send_json(
                            await format_title_response(
                                tree=tree,
                                user_id=user_id,
                                conversation_id=data["conversation_id"],
                                query_id=data["query_id"],
                            )
                        )

                    # Add token usage to completed payload
                    if not tree.low_memory:
                        token_usage = {
                            "base_lm": {
                                "calls": tree.tracker.get_num_calls("base_lm"),
                                "input_tokens": tree.tracker.get_total_input_tokens("base_lm") or 0,
                                "output_tokens": tree.tracker.get_total_output_tokens("base_lm") or 0,
                                "total_tokens": (tree.tracker.get_total_input_tokens("base_lm") or 0) + (tree.tracker.get_total_output_tokens("base_lm") or 0),
                                "cost": tree.tracker.get_total_cost("base_lm") or 0.0,
                                "avg_input_tokens": tree.tracker.get_average_input_tokens("base_lm") or 0,
                                "avg_output_tokens": tree.tracker.get_average_output_tokens("base_lm") or 0,
                                "avg_cost": tree.tracker.get_average_cost("base_lm") or 0.0,
                            },
                            "complex_lm": {
                                "calls": tree.tracker.get_num_calls("complex_lm"),
                                "input_tokens": tree.tracker.get_total_input_tokens("complex_lm") or 0,
                                "output_tokens": tree.tracker.get_total_output_tokens("complex_lm") or 0,
                                "total_tokens": (tree.tracker.get_total_input_tokens("complex_lm") or 0) + (tree.tracker.get_total_output_tokens("complex_lm") or 0),
                                "cost": tree.tracker.get_total_cost("complex_lm") or 0.0,
                                "avg_input_tokens": tree.tracker.get_average_input_tokens("complex_lm") or 0,
                                "avg_output_tokens": tree.tracker.get_average_output_tokens("complex_lm") or 0,
                                "avg_cost": tree.tracker.get_average_cost("complex_lm") or 0.0,
                            },
                        }
                        # Add token usage to payload if it exists
                        if "payload" in yielded_result:
                            yielded_result["payload"]["token_usage"] = token_usage
                        else:
                            yielded_result["token_usage"] = token_usage

                    # send the completed payload
                    await websocket.send_json(yielded_result)

            except WebSocketDisconnect:
                logger.info("Client disconnected during processing")
                break
            # Add a small delay between messages to prevent overwhelming
            await asyncio.sleep(0.005)
            # logger.debug(f"Sent message to client: {yielded_result}")

    except Exception as e:
        logger.exception(f"Error in /query API")

        if "conversation_id" in data:
            error = error_payload(
                text=f"{str(e)}",
                conversation_id=data["conversation_id"],
                query_id=data["query_id"],
            )
            await websocket.send_json(error)
        else:
            error = error_payload(
                text=f"{str(e)}",
                conversation_id="",
                query_id="",
            )
            await websocket.send_json(error)


# Process endpoint
@router.websocket("/query")
async def query_websocket(
    websocket: WebSocket, user_manager: UserManager = Depends(get_user_manager)
):
    """
    WebSocket endpoint for processing pipelines.
    Handles real-time communication for pipeline execution and status updates.
    """
    authorization = websocket.headers.get("authorization")
    token = websocket.query_params.get("token")
    if not authorization and token:
        authorization = f"Bearer {token}"
    try:
        authenticated_user_id, _ = _validate_token(authorization)
    except HTTPException as exc:
        await websocket.close(code=1008, reason=str(exc.detail))
        return

    await help_websocket(
        websocket,
        lambda data, ws: process(data, ws, user_manager, authenticated_user_id=authenticated_user_id),
    )

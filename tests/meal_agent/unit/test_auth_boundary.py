import pytest
from fastapi import HTTPException

from elysia.api.routes.auth import _issue_token, require_matching_user_id
from elysia.api.routes.db import _shopping_item_filter


def _bearer(user_id: str) -> str:
    return f"Bearer {_issue_token(user_id)}"


def test_require_matching_user_id_accepts_matching_token():
    assert require_matching_user_id("user_123", _bearer("user_123")) == "user_123"


def test_require_matching_user_id_rejects_missing_token():
    with pytest.raises(HTTPException) as exc:
        require_matching_user_id("user_123", None)

    assert exc.value.status_code == 401


def test_require_matching_user_id_rejects_mismatched_token():
    with pytest.raises(HTTPException) as exc:
        require_matching_user_id("user_123", _bearer("other_user"))

    assert exc.value.status_code == 403


def test_shopping_item_filter_scopes_list_items_by_user():
    filter_obj = _shopping_item_filter("shared_list_id", "user_123", "tomato")
    targets = {filter_value.target for filter_value in filter_obj.filters}

    assert targets == {"list_id", "user_id", "ingredient_name"}

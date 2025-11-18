from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from weaviate.collections.classes.filters import Filter, _Filters

logger = logging.getLogger(__name__)

_VALUE_KEYS_PRIORITY: tuple[str, ...] = (
    "valueTextArray",
    "valueText",
    "valueString",
    "valueBoolean",
    "valueInt",
    "valueNumber",
    "valueFloat",
    "valueDate",
    "valueGeoRange",
)


def _extract_value(where: dict[str, Any]) -> Any:
    for key in _VALUE_KEYS_PRIORITY:
        if key in where:
            return where[key]
    raise ValueError("Unsupported where-clause value payload")


def _build_property_filter(path: list[str]) -> Optional[_Filters]:
    if not path:
        return None

    if len(path) == 1:
        return Filter.by_property(path[0])

    # Old-style Weaviate paths alternate between reference property and target collection.
    if len(path) >= 3 and len(path) % 2 == 1:
        ref = Filter.by_ref_multi_target(path[0], path[1])
        idx = 2
        while idx < len(path) - 1:
            next_ref = path[idx]
            next_target = path[idx + 1]
            if idx + 2 >= len(path):
                break
            ref = ref.by_ref_multi_target(next_ref, next_target)
            idx += 2
        return ref.by_property(path[-1])

    # Fallback: use the final property name on the root object.
    logger.debug("Falling back to root-level property filter for path=%s", path)
    return Filter.by_property(path[-1])


def _apply_operator(property_filter: _Filters, operator: str, value: Any) -> Optional[_Filters]:
    op = operator or "Equal"
    op = op.capitalize()

    try:
        if op == "Equal":
            return property_filter.equal(value)
        if op == "Notequal":
            return property_filter.not_equal(value)
        if op == "Containsany":
            assert isinstance(value, Iterable), "contains_any expects iterable"
            return property_filter.contains_any(value)
        if op == "Containsall":
            assert isinstance(value, Iterable), "contains_all expects iterable"
            return property_filter.contains_all(value)
        if op == "Lessthanequal":
            return property_filter.less_or_equal(value)
        if op == "Greaterthanequal":
            return property_filter.greater_or_equal(value)
        if op == "Lessthan":
            return property_filter.less_than(value)
        if op == "Greaterthan":
            return property_filter.greater_than(value)
        if op == "Like":
            return property_filter.like(value)
        if op == "Isnull":
            return property_filter.is_none(bool(value))
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning("Failed to build filter for operator %s: %s", operator, exc)
        return None

    logger.warning("Unsupported where-clause operator: %s", operator)
    return None


def build_filters_from_where(where: Optional[dict[str, Any]]) -> Optional[_Filters]:
    """
    Convert legacy GraphQL-style where clauses into Weaviate collection filters.

    Returns:
        _Filters instance or None if no valid filter could be produced.
    """

    if where is None:
        return None

    operator = where.get("operator")

    if operator in {"And", "OR", "Or"}:
        operands = where.get("operands", [])
        built_operands = [
            build_filters_from_where(operand) for operand in operands if operand is not None
        ]
        built_operands = [operand for operand in built_operands if operand is not None]

        if not built_operands:
            return None

        if operator.lower() == "and":
            return Filter.all_of(built_operands)
        return Filter.any_of(built_operands)

    if operator and operator.lower() == "not":
        logger.warning("NOT operator is not supported in fetch_objects filters; ignoring clause.")
        return None

    property_filter = _build_property_filter(where.get("path", []))
    if property_filter is None:
        return None

    try:
        value = _extract_value(where)
    except ValueError as exc:
        logger.warning("Failed to extract where-clause value: %s", exc)
        return None

    return _apply_operator(property_filter, operator or "Equal", value)



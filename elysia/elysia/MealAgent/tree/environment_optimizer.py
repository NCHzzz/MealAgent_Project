"""
Environment Optimizer - Reduces token usage by summarizing and pruning environment data.

This module provides:
1. Environment summarization for large result sets
2. Result deduplication detection
3. Context pruning for old/unnecessary data
4. Early completion detection
"""

from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)

# Constants
MAX_OBJECTS_IN_ENV = 50  # Maximum objects to keep in environment per tool
MAX_ENV_SIZE_TOKENS = 10000  # Estimated max tokens for environment
SUMMARY_THRESHOLD = 20  # Summarize if more than this many objects


def summarize_objects(objects: List[Dict], max_items: int = 10) -> Dict[str, Any]:
    """
    Summarize a list of objects to reduce token usage.
    
    Args:
        objects: List of objects to summarize
        max_items: Maximum number of items to include in summary
        
    Returns:
        Summary dictionary with count, sample items, and key fields
    """
    if not objects:
        return {"count": 0, "items": []}
    
    if len(objects) <= max_items:
        return {"count": len(objects), "items": objects}
    
    # Get sample items
    sample = objects[:max_items]
    
    # Extract common fields from all objects
    if sample:
        common_fields = set(sample[0].keys())
        for obj in sample[1:]:
            common_fields &= set(obj.keys())
    else:
        common_fields = set()
    
    return {
        "count": len(objects),
        "sample_count": len(sample),
        "items": sample,
        "common_fields": list(common_fields),
        "summary": f"{len(objects)} items (showing {len(sample)} samples)",
    }


def optimize_environment(environment: Dict[str, Dict[str, List]], max_objects: int = MAX_OBJECTS_IN_ENV) -> Dict[str, Dict[str, List]]:
    """
    Optimize environment by summarizing large result sets.
    
    Args:
        environment: Environment dictionary
        max_objects: Maximum objects to keep per tool result
        
    Returns:
        Optimized environment dictionary
    """
    optimized = {}
    
    for tool_name, tool_results in environment.items():
        if tool_name == "SelfInfo":
            optimized[tool_name] = tool_results
            continue
        
        optimized[tool_name] = {}
        
        for result_name, result_list in tool_results.items():
            if not result_list:
                optimized[tool_name][result_name] = result_list
                continue
            
            optimized_results = []
            
            for result_item in result_list:
                if not isinstance(result_item, dict) or "objects" not in result_item:
                    optimized_results.append(result_item)
                    continue
                
                objects = result_item.get("objects", [])
                
                # If too many objects, summarize
                if len(objects) > max_objects:
                    logger.info(
                        f"Summarizing {tool_name}/{result_name}: {len(objects)} objects -> {max_objects} samples"
                    )
                    
                    # Create summary
                    summary = summarize_objects(objects, max_items=max_objects)
                    
                    # Replace objects with summary
                    optimized_item = result_item.copy()
                    optimized_item["objects"] = summary["items"]
                    optimized_item["_summary"] = summary
                    optimized_item["_original_count"] = summary["count"]
                    
                    optimized_results.append(optimized_item)
                else:
                    optimized_results.append(result_item)
            
            optimized[tool_name][result_name] = optimized_results
    
    return optimized


def detect_duplicate_queries(environment: Dict[str, Dict[str, List]], current_query: str) -> bool:
    """
    Detect if current query is similar to previous queries.
    
    Args:
        environment: Environment dictionary
        current_query: Current query text
        
    Returns:
        True if duplicate query detected
    """
    # Check query_tool results for similar queries
    if "query_tool" in environment:
        for result_name, results in environment["query_tool"].items():
            for result_item in results:
                metadata = result_item.get("metadata", {})
                prev_query = metadata.get("query", "")
                
                # Simple similarity check
                if prev_query and current_query:
                    # Normalize queries
                    prev_norm = prev_query.lower().strip()
                    curr_norm = current_query.lower().strip()
                    
                    # Check if very similar
                    if prev_norm == curr_norm or (
                        len(prev_norm) > 10 and 
                        len(curr_norm) > 10 and
                        prev_norm in curr_norm or curr_norm in prev_norm
                    ):
                        logger.warning(f"Duplicate query detected: '{current_query}'' similar to '{prev_query}'")
                        return True
    
    return False


def detect_task_completion(environment: Dict[str, Dict[str, List]], user_prompt: str) -> bool:
    """
    Detect if task has been completed based on environment state.
    
    Args:
        environment: Environment dictionary
        user_prompt: Original user prompt
        
    Returns:
        True if task appears completed
    """
    prompt_lower = user_prompt.lower()
    
    # Check for query/search tasks
    if any(kw in prompt_lower for kw in ["find", "search", "identify", "list", "show"]):
        # Check if query_tool has results
        if "query_tool" in environment:
            for result_name, results in environment["query_tool"].items():
                for result_item in results:
                    objects = result_item.get("objects", [])
                    if objects:
                        count = result_item.get("metadata", {}).get("count", len(objects))
                        if count > 0:
                            logger.info(f"Task completion detected: Found {count} results for query")
                            return True
    
    # Check for calculation tasks
    if any(kw in prompt_lower for kw in ["calculate", "compute", "total"]):
        if "nutrition_calc_tool" in environment or "macro_calc_tool" in environment:
            logger.info("Task completion detected: Calculation completed")
            return True
    
    # Check for planning tasks
    if any(kw in prompt_lower for kw in ["plan", "create plan", "generate"]):
        if "plan_assemble_day_tool" in environment or "plan_assemble_weekly_tool" in environment:
            logger.info("Task completion detected: Plan created")
            return True
    
    return False


def prune_old_environment_data(
    environment: Dict[str, Dict[str, List]], 
    keep_recent: int = 2
) -> Dict[str, Dict[str, List]]:
    """
    Prune old environment data, keeping only recent results.
    
    Args:
        environment: Environment dictionary
        keep_recent: Number of recent results to keep per tool
        
    Returns:
        Pruned environment dictionary
    """
    pruned = {}
    
    for tool_name, tool_results in environment.items():
        if tool_name == "SelfInfo":
            pruned[tool_name] = tool_results
            continue
        
        pruned[tool_name] = {}
        
        for result_name, result_list in tool_results.items():
            if not result_list:
                pruned[tool_name][result_name] = result_list
                continue
            
            # Keep only most recent results
            if len(result_list) > keep_recent:
                logger.info(
                    f"Pruning {tool_name}/{result_name}: {len(result_list)} -> {keep_recent} results"
                )
                pruned[tool_name][result_name] = result_list[-keep_recent:]
            else:
                pruned[tool_name][result_name] = result_list
    
    return pruned











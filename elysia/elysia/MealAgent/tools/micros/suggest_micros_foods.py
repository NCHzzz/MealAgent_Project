"""
Suggest foods rich in deficient micronutrients.
"""
from typing import AsyncGenerator, Dict, Any, List

from elysia.tree.objects import TreeData
from elysia.objects import Result, Error, Response
from elysia.util.client import ClientManager
from elysia import tool
import dspy
from elysia.util.elysia_chain_of_thought import ElysiaChainOfThought


@tool
async def suggest_micros_foods_tool(
    tree_data: TreeData,
    client_manager: ClientManager,
    deficient_nutrients: List[str] | None = None,
    top_k: int = 10,
    base_lm=None,
    **kwargs,
) -> AsyncGenerator[Result | str | Error, None]:
    """
    Suggest foods rich in deficient micronutrients.

    Environment reads:
      - environment["micronutrient_check_tool"]["micros"] (optional - if deficient_nutrients not provided)
    Environment writes:
      - environment["suggest_micros_foods_tool"]["suggestions"]
    """
    yield Response("Finding foods rich in deficient nutrients...")

    # Get deficient nutrients
    if not deficient_nutrients:
        micros_results = tree_data.environment.find("micronutrient_check_tool", "micros")
        if micros_results and micros_results[0].objects:
            # For MVP, assume we need to identify deficiencies based on RDAs
            # This is simplified - in production, compare against RDA values
            yield Response("Note: Deficient nutrients should be provided or calculated from RDAs")
            deficient_nutrients = []  # Would be populated from RDA comparison
        else:
            yield Error("deficient_nutrients required or run micronutrient_check_tool first")
            return

    if not deficient_nutrients:
        yield Error("No deficient nutrients identified")
        return

    try:
        client = client_manager.get_client()
        fdc_collection = client.collections.get("FdcFood")

        # Map nutrient names to FdcFood fields
        nutrient_field_map = {
            "calcium_mg": "calcium_mg_100g",
            "iron_mg": "iron_mg_100g",
            "potassium_mg": "potassium_mg_100g",
            "vitamin_c_mg": "vitamin_c_mg_100g",
            "vitamin_a_IU": "vitamin_a_iu_100g",
        }

        # Search for foods rich in each deficient nutrient
        # Optimize: Query once and filter for all nutrients (more efficient than separate queries)
        # Note: For production, consider using Weaviate's where filters with GreaterThan
        # to query only foods with nutrient values above a threshold
        all_suggestions = []
        
        # Query once with higher limit to cover all nutrients
        # In production, consider using where filters: {"path": [field], "operator": "GreaterThan", "valueNumber": threshold}
        try:
            results = fdc_collection.query.fetch_objects(
                limit=500,  # Get larger pool to filter for all nutrients
            )
            
            # Process all nutrients from single query result
            for nutrient in deficient_nutrients:
                field = nutrient_field_map.get(nutrient)
                if not field:
                    continue
                
                # Filter and score by nutrient content
                scored_foods = []
                for obj in results.objects:
                    food = obj.properties
                    nutrient_value = float(food.get(field, 0.0))
                    if nutrient_value > 0:
                        scored_foods.append({
                            "fdc_id": food.get("fdc_id"),
                            "description": food.get("description", ""),
                            "nutrient": nutrient,
                            "nutrient_value": nutrient_value,
                            "nutrient_value_per_100g": nutrient_value,
                        })
                
                # Sort by nutrient value and take top
                scored_foods.sort(key=lambda x: x.get("nutrient_value", 0.0), reverse=True)
                all_suggestions.extend(scored_foods[:top_k])
        except Exception as e:
            yield Error(f"Failed to query FDC foods: {str(e)}")
            return

        # Deduplicate by fdc_id
        seen = set()
        unique_suggestions = []
        for sug in all_suggestions:
            fdc_id = sug.get("fdc_id")
            if fdc_id and fdc_id not in seen:
                seen.add(fdc_id)
                unique_suggestions.append(sug)

        suggestions_output = {
            "deficient_nutrients": deficient_nutrients,
            "suggestions": unique_suggestions[:top_k],
            "count": len(unique_suggestions[:top_k]),
        }

        yield Result(
            name="suggestions",
            objects=[suggestions_output],
            metadata={
                "suggestion_count": len(unique_suggestions[:top_k]),
                "deficient_count": len(deficient_nutrients),
            },
            payload_type="generic",
        )

        if unique_suggestions:
            yield Response(f"Found {len(unique_suggestions[:top_k])} food suggestions for deficient nutrients")
            # Optional CoT summary document when base_lm is available
            if base_lm:
                try:
                    class MicrosSummaryPrompt(dspy.Signature):
                        """
                        Create a brief user-facing summary of micronutrient suggestions.
                        Include which nutrients are deficient and the top 3 example foods with their key nutrient values.
                        Keep it concise and practical.
                        """
                        deficient = dspy.InputField(description="List of deficient nutrient keys (e.g., calcium_mg).")
                        suggestions = dspy.InputField(description="List of suggestion dicts with description and nutrient_value.")
                        message_update = dspy.OutputField(description="One sentence update about generating the summary.")
                        summary = dspy.OutputField(description="Concise markdown summary text.")

                    cot = ElysiaChainOfThought(
                        MicrosSummaryPrompt,
                        tree_data=tree_data,
                        reasoning=False,
                        impossible=False,
                        message_update=True,
                        environment=False,
                        tasks_completed=False,
                    )
                    # Pick top 3 to keep prompt small
                    top_examples = unique_suggestions[: min(3, len(unique_suggestions))]
                    pred = await cot.aforward(
                        lm=base_lm,
                        deficient=deficient_nutrients,
                        suggestions=top_examples,
                    )
                    if getattr(pred, "message_update", None):
                        yield Response(str(pred.message_update))
                    summary_text = str(getattr(pred, "summary", "")).strip()
                    if summary_text:
                        yield Result(
                            name="micros_summary",
                            objects=[{"content": summary_text}],
                            metadata={"deficient": deficient_nutrients, "count": len(unique_suggestions[:top_k])},
                            payload_type="document",
                            mapping={
                                "content": "content",
                                "title": "",
                                "author": "",
                                "date": "",
                                "category": "",
                            },
                        )
                except Exception:
                    # Non-fatal if CoT summary fails
                    pass
        else:
            yield Response("No suitable foods found")

    except Exception as e:
        yield Error(f"Micros food suggestion failed: {str(e)}")
        return


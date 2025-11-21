import React, { useContext } from "react";
import { ResultPayload } from "@/app/types/chat";
import {
  ProductPayload,
  ThreadPayload,
  SingleMessagePayload,
  AggregationPayload,
  DocumentPayload,
  TicketPayload,
  MealPlanPayload,
  RecipeCardPayload,
  NutritionSummaryPayload,
  ShoppingListPayload,
  CookingStepsPayload,
  MealHistoryPayload,
} from "@/app/types/displays";

import TicketsDisplay from "./displays/Ticket/TicketDisplay";
import ProductDisplay from "./displays/Product/ProductDisplay";
import ThreadDisplay from "./displays/MessageThread/ThreadDisplay";
import SingleMessageDisplay from "./displays/MessageThread/SingleMessageDisplay";
import BoringGenericDisplay from "./displays/Generic/BoringGeneric";
import AggregationDisplay from "./displays/ChartTable/AggregationDisplay";
import DocumentDisplay from "./displays/Document/DocumentDisplay";
import BarDisplay from "./displays/ChartTable/BarDisplay";
import ScatterOrLineDisplay from "./displays/ChartTable/ScatterOrLineDisplay";
import HistogramDisplay from "./displays/ChartTable/HistogramDisplay";
// MealAgent custom displays
import MealPlanDisplay from "./displays/meal_agent/MealPlanDisplay";
import RecipeCard from "./displays/meal_agent/RecipeCard";
import RecipeDetail from "./displays/meal_agent/RecipeDetail";
import NutritionSummary from "./displays/meal_agent/NutritionSummary";
import ShoppingListDisplay from "./displays/meal_agent/ShoppingListDisplay";
import CookingStepsDisplay from "./displays/meal_agent/CookingStepsDisplay";
import MealHistoryDisplay from "./displays/meal_agent/MealHistoryDisplay";
import { DisplayContext } from "../contexts/DisplayContext";

interface RenderDisplayProps {
  payload: ResultPayload;
  index: number;
  messageId: string;
  handleResultPayloadChange: (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any,
    collection_name: string
  ) => void;
}

const RenderDisplay: React.FC<RenderDisplayProps> = ({
  payload,
  index,
  messageId,
  handleResultPayloadChange,
}) => {
  const keyBase = `${index}-${messageId}`;
  const { currentCollectionName } = useContext(DisplayContext);

  const handleResultPayloadChangeWithCollectionName = (
    type: string,
    payload: /* eslint-disable @typescript-eslint/no-explicit-any */ any
  ) => {
    handleResultPayloadChange(type, payload, currentCollectionName);
  };

  switch (payload.type) {
    case "ticket":
      return (
        <TicketsDisplay
          key={`${keyBase}-tickets`}
          tickets={payload.objects as TicketPayload[]}
          handleResultPayloadChange={
            handleResultPayloadChangeWithCollectionName
          }
        />
      );
    case "product":
    case "ecommerce":
      return (
        <ProductDisplay
          key={`${keyBase}-product`}
          products={payload.objects as ProductPayload[]}
          handleResultPayloadChange={
            handleResultPayloadChangeWithCollectionName
          }
        />
      );
    case "conversation":
      return (
        <ThreadDisplay
          key={`${keyBase}-conversation`}
          payload={payload.objects as ThreadPayload[]}
          handleResultPayloadChange={
            handleResultPayloadChangeWithCollectionName
          }
        />
      );
    case "message":
      return (
        <SingleMessageDisplay
          key={`${keyBase}-message`}
          payload={payload.objects as SingleMessagePayload[]}
        />
      );
    // MealAgent custom displays
    case "meal_plan":
      return (
        <MealPlanDisplay
          key={`${keyBase}-meal-plan`}
          plans={payload.objects as MealPlanPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "recipe_card":
      return (
        <RecipeCard
          key={`${keyBase}-recipe-card`}
          recipes={payload.objects as RecipeCardPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "recipe_detail":
      const recipeDetail = payload.objects[0] as RecipeCardPayload;
      return (
        <RecipeDetail
          key={`${keyBase}-recipe-detail`}
          recipe={recipeDetail}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "nutrition_summary":
      return (
        <NutritionSummary
          key={`${keyBase}-nutrition-summary`}
          summaries={payload.objects as NutritionSummaryPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "shopping_list":
      return (
        <ShoppingListDisplay
          key={`${keyBase}-shopping-list`}
          lists={payload.objects as ShoppingListPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "cooking_steps":
      return (
        <CookingStepsDisplay
          key={`${keyBase}-cooking-steps`}
          steps={payload.objects as CookingStepsPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "meal_history":
      return (
        <MealHistoryDisplay
          key={`${keyBase}-meal-history`}
          history={payload.objects as MealHistoryPayload[]}
          handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
        />
      );
    case "generic":
    case "table":
    case "mapped":
      // Auto-detect MealAgent data from metadata or object structure
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const objects = payload.objects as { [key: string]: any }[];
      if (objects.length > 0) {
        const firstObj = objects[0];
        const metadata = payload.metadata || {};

        // Detect meal plan from metadata or object structure
        if (
          metadata.plan_type === "day" ||
          metadata.plan_type === "week" ||
          firstObj.plan_type === "day" ||
          firstObj.plan_type === "week"
        ) {
          return (
            <MealPlanDisplay
              key={`${keyBase}-meal-plan-auto`}
              plans={objects as MealPlanPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }

        // Detect cooking steps from metadata or object structure
        if (
          metadata.tool === "cook_mode_tool" ||
          metadata.steps_count !== undefined ||
          (firstObj.steps && Array.isArray(firstObj.steps))
        ) {
          return (
            <CookingStepsDisplay
              key={`${keyBase}-cooking-steps-auto`}
              steps={objects as CookingStepsPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }

        // Detect recipe cards from object structure (has food_id, dish_name, macros_per_serving)
        if (
          firstObj.food_id &&
          firstObj.dish_name &&
          firstObj.macros_per_serving
        ) {
          return (
            <RecipeCard
              key={`${keyBase}-recipe-card-auto`}
              recipes={objects as RecipeCardPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }

        // Detect shopping list from object structure
        if (
          firstObj.items &&
          Array.isArray(firstObj.items) &&
          firstObj.items.length > 0 &&
          firstObj.items[0].ingredient_name
        ) {
          return (
            <ShoppingListDisplay
              key={`${keyBase}-shopping-list-auto`}
              lists={objects as ShoppingListPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }

        // Detect nutrition summary from object structure
        if (
          firstObj.total_macros &&
          firstObj.total_macros.kcal !== undefined
        ) {
          return (
            <NutritionSummary
              key={`${keyBase}-nutrition-summary-auto`}
              summaries={objects as NutritionSummaryPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }

        // Detect meal history from object structure
        if (
          firstObj.log_id &&
          firstObj.logged_at &&
          firstObj.calculated_macros
        ) {
          return (
            <MealHistoryDisplay
              key={`${keyBase}-meal-history-auto`}
              history={objects as MealHistoryPayload[]}
              handleResultPayloadChange={handleResultPayloadChangeWithCollectionName}
            />
          );
        }
      }

      // Fallback to generic table display
      return (
        <BoringGenericDisplay
          key={`${keyBase}-boring-generic`}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          payload={objects}
        />
      );
    case "aggregation":
      return (
        <AggregationDisplay
          key={`${keyBase}-aggregation`}
          aggregation={payload.objects as AggregationPayload[]}
        />
      );
    case "document":
      return (
        <DocumentDisplay
          key={`${keyBase}-document`}
          payload={payload.objects as DocumentPayload[]}
          handleResultPayloadChange={
            handleResultPayloadChangeWithCollectionName
          }
        />
      );
    case "bar_chart":
      return <BarDisplay key={`${keyBase}-chart`} result={payload} />;
    case "scatter_or_line_chart":
      return <ScatterOrLineDisplay key={`${keyBase}-chart`} result={payload} />;
    case "histogram_chart":
      return <HistogramDisplay key={`${keyBase}-chart`} result={payload} />;
    default:
      if (process.env.NODE_ENV === "development") {
        console.warn("Unhandled ResultPayload type:", payload.type);
      }
      return null;
  }
};

export default RenderDisplay;

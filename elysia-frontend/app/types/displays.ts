export type DefaultResultPayload = {
  uuid?: string;
  ELYSIA_SUMMARY?: string;
  _REF_ID?: string;
};

export type AggregationPayload = {
  num_items: number;
  collections: AggregationData[];
  _REF_ID?: string;
};

export type AggregationData = {
  [key: string]: AggregationCollection;
};

export type AggregationCollection = {
  [key: string]: AggregationField;
};

export type AggregationField = {
  type: "text" | "number";
  values: AggregationValue[];
  groups?: { [key: string]: AggregationCollection };
};

export type AggregationValue = {
  value: string | number;
  field: string | null;
  aggregation: "count" | "sum" | "avg" | "minimum" | "maximum" | "mean";
};

export type DocumentPayload = DefaultResultPayload & {
  title: string;
  author: string;
  date: string;
  content?: string;
  category: string | string[];
  chunk_spans: ChunkSpan[];
  collection_name: string;
};

export type BarPayload = DefaultResultPayload & {
  title: string;
  description: string;
  x_axis_label: string;
  y_axis_label: string;
  data: {
    x_labels: string[] | number[];
    y_values: { [key: string]: number[] | string[] };
  };
};

export type HistogramPayload = DefaultResultPayload & {
  title: string;
  description: string;
  data: {
    [key: string]: {
      distribution: number[] | string[];
    };
  };
};

export type ScatterOrLinePayload = DefaultResultPayload & {
  title: string;
  description: string;
  x_axis_label: string;
  y_axis_label: string;
  data: ScatterOrLineDataPoints;
};

export type ScatterOrLineDataPoints = {
  x_axis: ScatterOrLineDataPoint[];
  y_axis: ScatterOrLineYAxisData[];
  normalize_y_axis: boolean;
};

export type ScatterOrLineYAxisData = {
  label: string;
  kind: "scatter" | "line";
  data_points: ScatterOrLineDataPoint[];
};

export type ScatterOrLineDataPoint = {
  value: number | string | Date;
  label: string | null;
};

export type ChartValue = {
  label: string;
  data: number[];
};

export type ChunkSpan = {
  start: number;
  end: number;
  uuid: string;
};

export type ProductPayload = DefaultResultPayload & {
  subcategory?: string;
  description?: string;
  reviews?: string[] | number;
  collection?: string;
  tags?: string[];
  sizes?: string[];
  product_id?: string;
  image?: string;
  url?: string;
  rating?: number;
  price?: number;
  category?: string;
  colors?: string[];
  brand?: string;
  name?: string;
  id?: string;
};

export type TicketPayload = DefaultResultPayload & {
  updated_at: string;
  title: string;
  subtitle: string;
  content: string;
  created_at: string;
  author: string;
  url: string;
  status: string;
  id: string;
  tags?: string[];
  comments: number | string[];
};

export type ThreadPayload = DefaultResultPayload & {
  conversation_id: string;
  messages: SingleMessagePayload[];
};

export type SingleMessagePayload = DefaultResultPayload & {
  relevant: boolean;
  conversation_id: number;
  message_id: string;
  author: string;
  content: string;
  timestamp: string;
};

// MealAgent-specific payload types
type MealRecipe = {
  food_id: string;
  dish_name: string;
  macros_per_serving?: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  allergens?: string[];
  cooking_time?: number;
  image_link?: string;
};

type MealComponent = {
  meal_type?: string;
  type?: string;
  recipe: MealRecipe;
  servings: number;
  macros?: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
};

export type MealPlanPayload = DefaultResultPayload & {
  plan_type: "day" | "week";
  meals?: {
    [mealKey: string]: MealComponent & {
      accompaniments?: MealComponent[];
    };
  };
  days?: {
    [dayKey: string]: {
      date: string;
      meals: {
        [mealKey: string]: MealComponent & {
          accompaniments?: MealComponent[];
        };
      };
      total_macros: {
        kcal: number;
        protein_g: number;
        fat_g: number;
        carb_g: number;
      };
    };
  };
  total_macros: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  average_daily_macros?: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  validation: {
    valid: boolean;
    macro_validation?: {
      valid: boolean;
      violations: any[];
      warnings: any[];
    };
    constraint_validation?: {
      valid: boolean;
      violations: any[];
    };
    variety_validation?: {
      valid: boolean;
      score: number;
    };
  };
  variety_score?: number;
  start_date?: string;
  created_at?: string | null;
};

export type RecipeCardPayload = DefaultResultPayload & {
  food_id: string;
  dish_name: string;
  dish_type?: string;
  serving_size?: number;
  cooking_time?: number;
  macros_per_serving?: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  allergens?: string[];
  diet_type?: string[];
  image_link?: string;
  ingredients?: string[];
  ingredients_with_qty?: string[];
};

export type NutritionSummaryPayload = DefaultResultPayload & {
  total_macros: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  targets?: {
    tdee_kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  micronutrients?: {
    [nutrient: string]: {
      total: number;
      target?: number;
      unit: string;
    };
  };
  validation?: {
    valid: boolean;
    violations: any[];
    warnings: any[];
  };
};

export type ShoppingListPayload = DefaultResultPayload & {
  items: {
    ingredient_name: string;
    quantity: number;
    unit: string;
    category?: string;
    fdc_id?: number;
  }[];
  original_count?: number;
  removed_count?: number;
  categories?: {
    [category: string]: {
      ingredient_name: string;
      quantity: number;
      unit: string;
    }[];
  };
};

export type CookingStepsPayload = DefaultResultPayload & {
  food_id: string;
  dish_name: string;
  steps: {
    index: number;
    instruction: string;
    estimated_seconds: number;
  }[];
  total_time_seconds?: number;
};

export type MealHistoryPayload = DefaultResultPayload & {
  log_id: string;
  logged_at: string;
  meal_description: string;
  parsed_dish?: string;
  calculated_macros: {
    kcal: number;
    protein_g: number;
    fat_g: number;
    carb_g: number;
  };
  calculated_micros?: {
    [nutrient: string]: number;
  };
  portion_size?: number;
};

export type CitationPreview = {
  type:
    | "text"
    | "ticket"
    | "message"
    | "conversation"
    | "product"
    | "ecommerce"
    | "generic"
    | "table"
    | "aggregation"
    | "mapped"
    | "document"
    | "meal_plan"
    | "recipe_card"
    | "nutrition_summary"
    | "shopping_list"
    | "cooking_steps"
    | "meal_history";
  title: string;
  text: string;
  index: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  object: any | null;
};

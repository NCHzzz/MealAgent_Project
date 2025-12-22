"""
Script để đánh giá chất lượng câu trả lời của chatbot MealAgent.

Usage:
    python scripts/evaluate_chatbot_quality.py --test-dataset test_cases_chatbot.json
    python scripts/evaluate_chatbot_quality.py --analyze-feedback
    python scripts/evaluate_chatbot_quality.py --all
    python scripts/evaluate_chatbot_quality.py --user-id test_user --conversation-id test_conv
"""

import argparse
import asyncio
import json
import statistics
import re
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
import math

try:
    import weaviate
    from weaviate.classes.query import Filter, Metrics
    from weaviate.classes.init import Auth
    from elysia.tree.tree import Tree
    from elysia.config import Settings
    from elysia.util.client import ClientManager
    from elysia.objects import Result, Response, Error, Status
    from elysia.api.utils.feedback import feedback_metadata
    from MealAgent.tree.meal_tree import build_meal_agent_tree
    WEAVIATE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import required modules: {e}")
    print("Some evaluation features may not be available.")
    WEAVIATE_AVAILABLE = False


class ChatbotQualityEvaluator:
    """Class để đánh giá chất lượng câu trả lời chatbot."""
    
    def __init__(self, output_dir: str = "chatbot_evaluation_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "evaluation_results": [],
            "summary": {}
        }
    
    def calculate_relevance_score(self, query: str, response: str) -> float:
        """
        Tính relevance score dựa trên keyword overlap và semantic similarity.
        """
        if not query or not response:
            return 0.0
        
        query_lower = query.lower()
        response_lower = response.lower()
        
        # Keyword overlap (weight: 0.4)
        query_words = set(query_lower.split())
        response_words = set(response_lower.split())
        
        if query_words:
            overlap = len(query_words & response_words) / len(query_words)
        else:
            overlap = 0.0
        
        # Semantic keywords matching (weight: 0.6)
        # Check for important keywords from query in response
        important_keywords = [
            word for word in query_words 
            if len(word) > 3 and word not in ['cho', 'tôi', 'bạn', 'của', 'với', 'và', 'the', 'a', 'an']
        ]
        
        if important_keywords:
            matched_keywords = sum(1 for kw in important_keywords if kw in response_lower)
            semantic_score = matched_keywords / len(important_keywords)
        else:
            semantic_score = overlap
        
        # Combine scores
        relevance = overlap * 0.4 + semantic_score * 0.6
        return min(relevance, 1.0)
    
    def calculate_accuracy_score(self, response: str, ground_truth: Optional[Dict] = None) -> float:
        """
        Tính accuracy score bằng cách kiểm tra:
        1. Expected actions/tools được gọi
        2. Expected content có trong response
        3. Không có contradictions
        """
        if not response:
            return 0.0
        
        response_lower = response.lower()
        score = 1.0
        
        if ground_truth:
            # Check expected content
            should_have = ground_truth.get("should_have", [])
            should_include = ground_truth.get("should_include", [])
            
            # Penalize nếu thiếu expected content
            missing_should_have = sum(1 for item in should_have if item.lower() not in response_lower)
            missing_should_include = sum(1 for item in should_include if item.lower() not in response_lower)
            
            total_expected = len(should_have) + len(should_include)
            if total_expected > 0:
                missing_ratio = (missing_should_have + missing_should_include) / total_expected
                score = 1.0 - (missing_ratio * 0.5)  # Max penalty: 50%
        
        # Check for common errors/contradictions
        # Negative keywords that shouldn't appear
        negative_patterns = [
            r'\bkhông\s+có\b',  # "không có" (don't have)
            r'\bkhông\s+tìm\s+thấy\b',  # "không tìm thấy" (not found)
            r'\berror\b',  # Error messages
            r'\bfailed\b',  # Failed messages
        ]
        
        for pattern in negative_patterns:
            if re.search(pattern, response_lower):
                score *= 0.7  # Penalize for errors
        
        return max(score, 0.0)
    
    def calculate_completeness_score(self, response: str, expected_topics: List[str]) -> float:
        """Tính completeness score - response có đề cập đến expected topics không."""
        if not expected_topics:
            return 1.0
        
        mentioned_topics = self.extract_topics(response)
        covered_topics = set(mentioned_topics) & set(expected_topics)
        
        return len(covered_topics) / len(expected_topics) if expected_topics else 1.0
    
    def calculate_clarity_score(self, response: str) -> float:
        """Tính clarity score dựa trên structure và readability."""
        if not response:
            return 0.0
        
        # Average sentence length
        sentences = [s.strip() for s in re.split(r'[.!?]+', response) if s.strip()]
        if not sentences:
            return 0.0
        
        avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
        
        # Has structure (headings, bullets, numbered lists)
        has_structure = bool(
            re.search(r'^[-*•]|^#|^\d+\.', response, re.MULTILINE) or
            'step' in response.lower() or
            'bước' in response.lower()
        )
        
        # Response length (not too short, not too long)
        word_count = len(response.split())
        length_score = 1.0 if 20 <= word_count <= 500 else 0.7
        
        # Combine scores
        clarity = (
            (1.0 if avg_sentence_length < 25 else 0.7) * 0.4 +
            (1.0 if has_structure else 0.5) * 0.3 +
            length_score * 0.3
        )
        
        return min(clarity, 1.0)
    
    def extract_topics(self, text: str) -> List[str]:
        """Extract topics từ text (simple keyword extraction)."""
        # Common topics/keywords
        topics = []
        text_lower = text.lower()
        
        topic_keywords = {
            "meal_plan": ["kế hoạch", "meal plan", "bữa ăn", "plan"],
            "nutrition": ["calo", "calories", "protein", "dinh dưỡng", "macro"],
            "cooking": ["nấu", "cook", "hướng dẫn", "steps", "bước"],
            "recipe": ["công thức", "recipe", "món ăn"],
            "constraints": ["ăn chay", "vegetarian", "allergen", "dị ứng"],
            "shopping": ["mua sắm", "shopping", "danh sách"],
            "pantry": ["tủ lạnh", "pantry", "kho"]
        }
        
        for topic, keywords in topic_keywords.items():
            if any(keyword in text_lower for keyword in keywords):
                topics.append(topic)
        
        return topics
    
    def calculate_overall_quality(self, scores: Dict[str, float]) -> float:
        """Tính overall quality score với weights."""
        weights = {
            "relevance": 0.25,
            "accuracy": 0.25,
            "completeness": 0.20,
            "helpfulness": 0.20,
            "clarity": 0.10
        }
        
        overall = sum(
            scores.get(metric, 0.0) * weight
            for metric, weight in weights.items()
        )
        
        return overall
    
    async def evaluate_response(
        self,
        query: str,
        response: str,
        test_case: Optional[Dict] = None
    ) -> Dict[str, float]:
        """Đánh giá một response."""
        expected_topics = test_case.get("expected_topics", []) if test_case else []
        ground_truth = test_case.get("ground_truth") if test_case else None
        
        scores = {
            "relevance": self.calculate_relevance_score(query, response),
            "accuracy": self.calculate_accuracy_score(response, ground_truth),
            "completeness": self.calculate_completeness_score(response, expected_topics),
            "clarity": self.calculate_clarity_score(response),
            "helpfulness": 0.8  # Placeholder - cần human evaluation hoặc user feedback
        }
        
        scores["overall"] = self.calculate_overall_quality(scores)
        
        return scores
    
    async def evaluate_test_dataset(
        self,
        test_cases: List[Dict],
        chatbot_processor=None,
        user_id: str = "eval_user",
        conversation_id: str = None
    ) -> List[Dict]:
        """
        Đánh giá test dataset.
        
        Args:
            test_cases: List of test cases với query và expected info
            chatbot_processor: Function để process query và get response
            user_id: User ID để test
            conversation_id: Conversation ID (auto-generated if None)
        """
        print(f"\n🔍 Đang đánh giá {len(test_cases)} test cases...")
        
        if conversation_id is None:
            conversation_id = f"eval_conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        evaluation_results = []
        
        for i, test_case in enumerate(test_cases, 1):
            query = test_case["query"]
            print(f"\n[{i}/{len(test_cases)}] Query: {query[:60]}...")
            
            start_time = datetime.now()
            
            # Get response từ chatbot
            if chatbot_processor:
                try:
                    response_data = await chatbot_processor(
                        query, 
                        user_id=user_id,
                        conversation_id=conversation_id
                    )
                    response = response_data.get("response", "")
                    tools_called = response_data.get("tools_called", [])
                    response_time = response_data.get("response_time", 0)
                except Exception as e:
                    print(f"  ⚠️ Error getting response: {e}")
                    import traceback
                    traceback.print_exc()
                    response = ""
                    tools_called = []
                    response_time = 0
            else:
                # Placeholder
                response = f"Response for: {query}"
                tools_called = []
                response_time = 0
            
            elapsed_time = (datetime.now() - start_time).total_seconds()
            
            # Evaluate response
            scores = await self.evaluate_response(query, response, test_case)
            
            # Check if expected tools were called
            expected_actions = test_case.get("expected_actions", [])
            tools_match_score = 1.0
            if expected_actions:
                matched_tools = len(set(tools_called) & set(expected_actions))
                tools_match_score = matched_tools / len(expected_actions) if expected_actions else 1.0
            
            result = {
                "query": query,
                "response": response[:1000] + "..." if len(response) > 1000 else response,
                "response_length": len(response),
                "full_response": response,  # Keep full response for analysis
                "tools_called": tools_called,
                "expected_actions": expected_actions,
                "tools_match_score": tools_match_score,
                "response_time": response_time or elapsed_time,
                "status_messages": response_data.get("status_messages", []),
                "errors": response_data.get("errors", []),
                "test_case": test_case,
                "scores": scores,
                "timestamp": datetime.now().isoformat()
            }
            
            evaluation_results.append(result)
            
            # Print scores
            print(f"  ⏱️  Response time: {result['response_time']:.2f}s")
            print(f"  📝 Response length: {result['response_length']} chars")
            print(f"  🔧 Tools called: {', '.join(tools_called) if tools_called else 'None'}")
            if expected_actions:
                match_status = "✅" if tools_match_score >= 0.8 else "⚠️"
                print(f"  {match_status} Tools match: {tools_match_score:.2f} (expected: {', '.join(expected_actions)})")
            if result.get("errors"):
                print(f"  ⚠️  Errors: {len(result['errors'])}")
            print(f"  📊 Relevance: {scores['relevance']:.2f}")
            print(f"  📊 Accuracy: {scores['accuracy']:.2f}")
            print(f"  📊 Completeness: {scores['completeness']:.2f}")
            print(f"  📊 Clarity: {scores['clarity']:.2f}")
            print(f"  📊 Overall: {scores['overall']:.2f}")
        
        self.results["evaluation_results"] = evaluation_results
        return evaluation_results
    
    def analyze_results(self, evaluation_results: List[Dict]) -> Dict[str, Any]:
        """Phân tích kết quả đánh giá."""
        if not evaluation_results:
            return {}
        
        # Calculate average scores
        all_scores = {
            "relevance": [r["scores"]["relevance"] for r in evaluation_results],
            "accuracy": [r["scores"]["accuracy"] for r in evaluation_results],
            "completeness": [r["scores"]["completeness"] for r in evaluation_results],
            "clarity": [r["scores"]["clarity"] for r in evaluation_results],
            "helpfulness": [r["scores"]["helpfulness"] for r in evaluation_results],
            "overall": [r["scores"]["overall"] for r in evaluation_results]
        }
        
        avg_scores = {
            metric: statistics.mean(scores)
            for metric, scores in all_scores.items()
        }
        
        # Identify weak areas (scores < 0.8)
        weak_areas = [
            metric for metric, score in avg_scores.items()
            if score < 0.8
        ]
        
        # Category breakdown
        category_scores = {}
        categories = set(
            r["test_case"].get("category", "unknown")
            for r in evaluation_results
            if r.get("test_case")
        )
        
        for category in categories:
            category_results = [
                r for r in evaluation_results
                if r.get("test_case", {}).get("category") == category
            ]
            if category_results:
                category_scores[category] = statistics.mean(
                    [r["scores"]["overall"] for r in category_results]
                )
        
        # Worst performing queries
        worst_queries = sorted(
            evaluation_results,
            key=lambda x: x["scores"]["overall"]
        )[:5]
        
        # Best performing queries
        best_queries = sorted(
            evaluation_results,
            key=lambda x: x["scores"]["overall"],
            reverse=True
        )[:5]
        
        # Average response time
        response_times = [r.get("response_time", 0) for r in evaluation_results if r.get("response_time", 0) > 0]
        avg_response_time = statistics.mean(response_times) if response_times else 0
        
        # Average response length
        response_lengths = [r.get("response_length", 0) for r in evaluation_results]
        avg_response_length = statistics.mean(response_lengths) if response_lengths else 0
        
        # Tools usage statistics
        all_tools_called = []
        for r in evaluation_results:
            all_tools_called.extend(r.get("tools_called", []))
        tool_usage = {}
        for tool in all_tools_called:
            tool_usage[tool] = tool_usage.get(tool, 0) + 1
        
        # Tools match statistics
        tools_match_scores = [r.get("tools_match_score", 1.0) for r in evaluation_results]
        avg_tools_match = statistics.mean(tools_match_scores) if tools_match_scores else 1.0
        
        # Error statistics
        total_errors = sum(len(r.get("errors", [])) for r in evaluation_results)
        queries_with_errors = sum(1 for r in evaluation_results if r.get("errors"))
        
        summary = {
            "total_evaluated": len(evaluation_results),
            "average_scores": avg_scores,
            "weak_areas": weak_areas,
            "category_scores": category_scores,
            "performance_metrics": {
                "average_response_time": avg_response_time,
                "average_response_length": avg_response_length,
                "average_tools_match": avg_tools_match,
                "total_errors": total_errors,
                "queries_with_errors": queries_with_errors,
                "error_rate": queries_with_errors / len(evaluation_results) if evaluation_results else 0
            },
            "tool_usage": tool_usage,
            "worst_queries": [
                {
                    "query": r["query"],
                    "overall_score": r["scores"]["overall"],
                    "scores": r["scores"],
                    "tools_called": r.get("tools_called", []),
                    "response_time": r.get("response_time", 0),
                    "errors": r.get("errors", [])
                }
                for r in worst_queries
            ],
            "best_queries": [
                {
                    "query": r["query"],
                    "overall_score": r["scores"]["overall"],
                    "scores": r["scores"],
                    "tools_called": r.get("tools_called", []),
                    "response_time": r.get("response_time", 0)
                }
                for r in best_queries
            ]
        }
        
        self.results["summary"] = summary
        return summary
    
    def print_summary(self, summary: Dict[str, Any]):
        """In tóm tắt kết quả."""
        print("\n" + "="*60)
        print("📊 TÓM TẮT ĐÁNH GIÁ CHẤT LƯỢNG CHATBOT")
        print("="*60)
        
        print(f"\n📈 Tổng số đánh giá: {summary.get('total_evaluated', 0)}")
        
        avg_scores = summary.get("average_scores", {})
        print("\n📊 Điểm Trung Bình:")
        for metric, score in avg_scores.items():
            status = "✅" if score >= 0.8 else "⚠️"
            print(f"  {status} {metric.capitalize()}: {score:.2f}")
        
        weak_areas = summary.get("weak_areas", [])
        if weak_areas:
            print(f"\n⚠️ Các điểm yếu (< 0.8): {', '.join(weak_areas)}")
        
        category_scores = summary.get("category_scores", {})
        if category_scores:
            print("\n📂 Điểm theo Category:")
            for category, score in category_scores.items():
                status = "✅" if score >= 0.8 else "⚠️"
                print(f"  {status} {category}: {score:.2f}")
        
        perf_metrics = summary.get("performance_metrics", {})
        print(f"\n⏱️  Performance Metrics:")
        print(f"  - Average Response Time: {perf_metrics.get('average_response_time', 0):.2f}s")
        print(f"  - Average Response Length: {perf_metrics.get('average_response_length', 0):.0f} chars")
        print(f"  - Average Tools Match: {perf_metrics.get('average_tools_match', 0):.2f}")
        print(f"  - Error Rate: {perf_metrics.get('error_rate', 0)*100:.1f}% ({perf_metrics.get('queries_with_errors', 0)}/{summary.get('total_evaluated', 0)} queries)")
        
        tool_usage = summary.get("tool_usage", {})
        if tool_usage:
            print("\n🔧 Tool Usage:")
            sorted_tools = sorted(tool_usage.items(), key=lambda x: x[1], reverse=True)
            for tool, count in sorted_tools[:5]:
                print(f"  - {tool}: {count} times")
        
        worst_queries = summary.get("worst_queries", [])
        if worst_queries:
            print("\n🔴 Top 5 Queries Kém Nhất:")
            for i, query_info in enumerate(worst_queries, 1):
                print(f"  {i}. {query_info['query'][:60]}...")
                print(f"     Overall Score: {query_info['overall_score']:.2f}")
                print(f"     Tools: {', '.join(query_info.get('tools_called', []))}")
        
        best_queries = summary.get("best_queries", [])
        if best_queries:
            print("\n🟢 Top 5 Queries Tốt Nhất:")
            for i, query_info in enumerate(best_queries, 1):
                print(f"  {i}. {query_info['query'][:60]}...")
                print(f"     Overall Score: {query_info['overall_score']:.2f}")
        
        print("\n" + "="*60)
    
    def save_results(self, filename: str = None):
        """Lưu kết quả vào file JSON."""
        if filename is None:
            filename = f"chatbot_evaluation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        output_path = self.output_dir / filename
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(self.results, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Kết quả đã được lưu vào: {output_path}")
        return output_path
    
    async def analyze_user_feedback(self, client=None, user_id: str = None):
        """Phân tích user feedback từ database."""
        print("\n📊 Đang phân tích user feedback...")
        
        if not client:
            print("  ⚠️ Client không có, bỏ qua phân tích feedback")
            print("  💡 Tip: Set WCD_URL and WCD_API_KEY environment variables để enable feedback analysis")
            return {}
        
        try:
            metadata = await feedback_metadata(client, user_id=user_id)
            
            total_feedback = metadata.get("total_feedback", 0)
            feedback_by_value = metadata.get("feedback_by_value", {})
            feedback_by_date = metadata.get("feedback_by_date", {})
            
            print(f"\n📈 Tổng số feedback: {total_feedback}")
            
            if total_feedback > 0:
                print("\n📊 Phân bố Feedback:")
                for value_name, count in feedback_by_value.items():
                    percentage = (count / total_feedback * 100) if total_feedback > 0 else 0
                    print(f"  - {value_name}: {count} ({percentage:.1f}%)")
                
                # Calculate average feedback score
                # Feedback values: negative=-2/-1, positive=1/2
                total_score = (
                    feedback_by_value.get("negative", 0) * -2 +
                    feedback_by_value.get("positive", 0) * 1 +
                    feedback_by_value.get("superpositive", 0) * 2
                )
                avg_feedback = total_score / total_feedback
                print(f"\n📊 Average Feedback Score: {avg_feedback:.2f}")
                
                # Calculate satisfaction rate (positive + superpositive)
                positive_count = (
                    feedback_by_value.get("positive", 0) +
                    feedback_by_value.get("superpositive", 0)
                )
                satisfaction_rate = (positive_count / total_feedback) * 100
                print(f"📊 Satisfaction Rate: {satisfaction_rate:.1f}%")
                
                # Recent feedback trend (last 7 days)
                if feedback_by_date:
                    recent_dates = sorted(feedback_by_date.keys(), reverse=True)[:7]
                    recent_feedback = [
                        feedback_by_date[date].get("mean", 0)
                        for date in recent_dates
                        if feedback_by_date[date].get("count", 0) > 0
                    ]
                    if recent_feedback:
                        recent_avg = statistics.mean(recent_feedback)
                        print(f"📊 Recent Average (7 days): {recent_avg:.2f}")
            else:
                print("  ℹ️  Chưa có feedback nào trong database")
            
            return metadata
            
        except Exception as e:
            print(f"  ⚠️ Error analyzing feedback: {e}")
            import traceback
            traceback.print_exc()
            return {}


async def load_test_dataset(file_path: str) -> List[Dict]:
    """Load test dataset từ file JSON."""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


async def create_sample_test_dataset(output_path: str = "test_cases.json"):
    """Tạo sample test dataset."""
    test_cases = [
        {
            "query": "Tạo kế hoạch bữa ăn hôm nay cho tôi",
            "expected_topics": ["meal plan", "daily plan", "breakfast", "lunch", "dinner"],
            "expected_actions": ["plan_day_e2e_tool"],
            "category": "meal_planning"
        },
        {
            "query": "Tôi muốn kế hoạch bữa ăn cho cả tuần",
            "expected_topics": ["weekly plan", "7 days", "variety"],
            "expected_actions": ["plan_week_e2e_tool"],
            "category": "meal_planning"
        },
        {
            "query": "Tôi cần bao nhiêu calo mỗi ngày?",
            "expected_topics": ["TDEE", "calories", "macros"],
            "expected_actions": ["macro_calc_tool"],
            "category": "nutrition"
        },
        {
            "query": "Hướng dẫn tôi nấu phở bò",
            "expected_topics": ["cooking", "steps", "recipe"],
            "expected_actions": ["cook_mode_tool"],
            "category": "cooking"
        },
        {
            "query": "Tôi ăn chay, không ăn đậu phộng",
            "expected_topics": ["vegetarian", "allergen", "constraints"],
            "expected_actions": ["constraints_guard_tool"],
            "category": "constraints"
        }
    ]
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(test_cases, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Sample test dataset đã được tạo: {output_path}")
    return test_cases


def extract_text_from_result(result) -> str:
    """
    Extract text content từ Result object dựa trên structure thực tế của Elysia.
    """
    text_parts = []
    
    if isinstance(result, Response):
        # Response objects có text trong objects[0]["text"]
        if result.objects and len(result.objects) > 0:
            if isinstance(result.objects[0], dict) and "text" in result.objects[0]:
                return result.objects[0]["text"]
        return str(result)
    
    elif isinstance(result, Result):
        # Result objects có objects list và metadata
        if result.objects:
            for obj in result.objects:
                if isinstance(obj, dict):
                    # Extract các fields có thể chứa text
                    if "text" in obj:
                        text_parts.append(str(obj["text"]))
                    elif "message" in obj:
                        text_parts.append(str(obj["message"]))
                    elif "title" in obj and "text" in obj:
                        text_parts.append(f"{obj.get('title', '')}: {obj.get('text', '')}")
                    elif "dish_name" in obj:
                        # Cooking steps result
                        dish_name = obj.get("dish_name", "")
                        steps = obj.get("steps", [])
                        if steps:
                            step_texts = [f"Bước {s.get('index', '')}: {s.get('instruction', '')}" for s in steps]
                            text_parts.append(f"{dish_name}\n" + "\n".join(step_texts))
                    elif "plan_type" in obj:
                        # Meal plan result
                        plan_type = obj.get("plan_type", "")
                        meals = obj.get("meals", {})
                        meal_texts = []
                        for meal_type, meal_data in meals.items():
                            recipe = meal_data.get("recipe", {})
                            dish_name = recipe.get("dish_name", "") if isinstance(recipe, dict) else ""
                            if dish_name:
                                meal_texts.append(f"{meal_type}: {dish_name}")
                        if meal_texts:
                            text_parts.append(f"Kế hoạch {plan_type}:\n" + "\n".join(meal_texts))
                    else:
                        # Fallback: convert dict to readable string
                        readable_items = []
                        for k, v in obj.items():
                            if isinstance(v, (str, int, float)):
                                readable_items.append(f"{k}: {v}")
                        if readable_items:
                            text_parts.append(", ".join(readable_items))
        
        # Add metadata info if relevant
        if result.metadata:
            tool_name = result.metadata.get("tool")
            if tool_name:
                # Tool name đã được track riêng, không cần add vào text
                pass
    
    elif isinstance(result, Status):
        # Status objects có text attribute
        if hasattr(result, "text"):
            return result.text
        elif hasattr(result, "object") and isinstance(result.object, dict):
            return result.object.get("text", str(result))
        return str(result)
    
    elif isinstance(result, Error):
        # Error objects có object với text
        if hasattr(result, "object") and isinstance(result.object, dict):
            return result.object.get("text", str(result))
        return str(result)
    
    elif isinstance(result, dict):
        # Handle dict results (from to_frontend)
        if "payload" in result:
            payload = result["payload"]
            if isinstance(payload, dict):
                if "text" in payload:
                    return payload["text"]
                elif "objects" in payload:
                    # Extract from objects
                    for obj in payload["objects"]:
                        if isinstance(obj, dict) and "text" in obj:
                            text_parts.append(obj["text"])
    
    return " ".join(text_parts).strip() if text_parts else str(result)


async def create_chatbot_processor(
    settings: Settings = None,
    client_manager: ClientManager = None
):
    """
    Tạo chatbot processor function để process queries và get responses.
    Dựa trên cách Tree.async_run() hoạt động và format của Response/Result objects.
    """
    if settings is None:
        settings = Settings()
    
    async def process_query(query: str, user_id: str, conversation_id: str) -> Dict[str, Any]:
        """
        Process query và return response.
        Extract responses từ Tree results đúng cách dựa trên Elysia structure.
        """
        query_id = str(uuid.uuid4())
        response_parts = []
        tools_called = set()  # Use set to avoid duplicates
        status_messages = []
        errors = []
        start_time = datetime.now()
        
        try:
            # Build tree
            tree = build_meal_agent_tree(
                settings=settings,
                user_id=user_id,
                conversation_id=conversation_id,
                user_prompt=query
            )
            
            # Process query - Tree.async_run() yields various objects
            async for result in tree.async_run(
                user_prompt=query,
                query_id=query_id,
                client_manager=client_manager,
                close_clients_after_completion=False
            ):
                # Skip None results
                if result is None:
                    continue
                
                # Extract text content based on object type
                text_content = extract_text_from_result(result)
                if text_content and text_content.strip():
                    response_parts.append(text_content.strip())
                
                # Track tools called from Result metadata
                if isinstance(result, Result):
                    metadata = result.metadata or {}
                    tool_name = metadata.get("tool")
                    if tool_name:
                        tools_called.add(tool_name)
                    # Also check function_name in metadata
                    function_name = metadata.get("function_name")
                    if function_name and function_name not in ["text_response", "forced_text_response"]:
                        tools_called.add(function_name)
                
                # Track status messages (for debugging)
                if isinstance(result, Status):
                    status_messages.append(text_content)
                
                # Track errors
                if isinstance(result, Error):
                    errors.append(text_content)
            
            # Combine response parts
            response = "\n".join(response_parts).strip()
            
            # If no response extracted, try to get from conversation history
            if not response and hasattr(tree, 'tree_data'):
                conversation_history = getattr(tree.tree_data, 'conversation_history', [])
                if conversation_history:
                    # Get last assistant message
                    for msg in reversed(conversation_history):
                        if isinstance(msg, dict) and msg.get("role") == "assistant":
                            response = msg.get("content", "")
                            break
            
            response_time = (datetime.now() - start_time).total_seconds()
            
            return {
                "response": response,
                "tools_called": list(tools_called),
                "response_time": response_time,
                "status_messages": status_messages,
                "errors": errors,
                "response_length": len(response)
            }
            
        except Exception as e:
            print(f"    ⚠️ Error processing query: {e}")
            import traceback
            traceback.print_exc()
            return {
                "response": f"Error: {str(e)}",
                "tools_called": [],
                "response_time": (datetime.now() - start_time).total_seconds(),
                "status_messages": [],
                "errors": [str(e)],
                "response_length": 0
            }
    
    return process_query


async def setup_weaviate_client():
    """Setup Weaviate client từ environment variables."""
    if not WEAVIATE_AVAILABLE:
        return None
    
    wcd_url = os.getenv("WCD_URL")
    wcd_api_key = os.getenv("WCD_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not wcd_url or not wcd_api_key:
        print("  ⚠️ WCD_URL or WCD_API_KEY not set, skipping Weaviate connection")
        return None
    
    try:
        headers = {}
        if openai_api_key:
            headers["X-OpenAI-API-Key"] = openai_api_key
        
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=wcd_url,
            auth_credentials=Auth.api_key(wcd_api_key),
            headers=headers
        )
        print("  ✅ Connected to Weaviate")
        return client
    except Exception as e:
        print(f"  ⚠️ Failed to connect to Weaviate: {e}")
        return None


async def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Đánh giá chất lượng chatbot")
    parser.add_argument("--test-dataset", help="Path đến test dataset JSON file")
    parser.add_argument("--analyze-feedback", action="store_true", help="Phân tích user feedback")
    parser.add_argument("--all", action="store_true", help="Chạy tất cả đánh giá")
    parser.add_argument("--create-sample", action="store_true", help="Tạo sample test dataset")
    parser.add_argument("--output-dir", default="chatbot_evaluation_results", help="Thư mục lưu kết quả")
    parser.add_argument("--user-id", default="eval_user", help="User ID để test")
    parser.add_argument("--conversation-id", help="Conversation ID (auto-generated if not provided)")
    
    args = parser.parse_args()
    
    evaluator = ChatbotQualityEvaluator(output_dir=args.output_dir)
    
    # Create sample dataset nếu được yêu cầu
    if args.create_sample:
        await create_sample_test_dataset("test_cases_chatbot.json")
        return
    
    # Setup Weaviate client
    client = await setup_weaviate_client()
    
    # Setup ClientManager
    client_manager = None
    if client:
        try:
            client_manager = ClientManager(client=client)
        except Exception as e:
            print(f"  ⚠️ Failed to create ClientManager: {e}")
    
    # Analyze feedback
    if args.analyze_feedback or args.all:
        await evaluator.analyze_user_feedback(client, user_id=args.user_id)
    
    # Evaluate test dataset
    if args.test_dataset or args.all:
        if args.test_dataset:
            test_cases = await load_test_dataset(args.test_dataset)
        else:
            # Use default test dataset
            default_path = "test_cases_chatbot.json"
            if os.path.exists(default_path):
                test_cases = await load_test_dataset(default_path)
            else:
                print(f"  ⚠️ Test dataset not found: {default_path}")
                print("  💡 Creating sample dataset...")
                test_cases = await create_sample_test_dataset(default_path)
        
        # Create chatbot processor
        settings = Settings()
        chatbot_processor = await create_chatbot_processor(
            settings=settings,
            client_manager=client_manager
        )
        
        # Run evaluation
        evaluation_results = await evaluator.evaluate_test_dataset(
            test_cases,
            chatbot_processor,
            user_id=args.user_id,
            conversation_id=args.conversation_id
        )
        
        # Analyze results
        summary = evaluator.analyze_results(evaluation_results)
        
        # Print summary
        evaluator.print_summary(summary)
        
        # Save results
        evaluator.save_results()
        
        # Save summary as separate file
        summary_path = evaluator.output_dir / f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Summary đã được lưu vào: {summary_path}")
    
    if not any([args.test_dataset, args.analyze_feedback, args.all, args.create_sample]):
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())


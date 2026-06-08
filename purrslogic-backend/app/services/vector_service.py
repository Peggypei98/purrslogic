import datetime
from typing import Any

from google import genai

from app.config.database import db

DEFAULT_USER_ID = "peggy_pei_28"
VECTOR_INDEX_NAME = "vector_index"
EMBEDDING_MODEL = "text-embedding-004"
EMBEDDING_DIMENSIONS = 768


def search_health_knowledge_base(query: str, limit: int = 2) -> list:
    """
    [Day 17 MCP Tool] Search Peggy's curated wellness knowledge base via MongoDB Atlas Vector Search.
    Use keywords such as 'cat', 'walk', 'recipe', or 'recovery' to retrieve semantic matches.
    """
    raise RuntimeError(
        "search_health_knowledge_base must be invoked through MongoDBVectorSearchService"
    )


class MongoDBVectorSearchService:
    def __init__(self):
        self.genai_client = genai.Client()
        self.embedding_model = EMBEDDING_MODEL
        self.collection = db["knowledge_base"]

    def _get_embedding(self, text: str) -> list[float]:
        response = self.genai_client.models.embed_content(
            model=self.embedding_model,
            contents=text,
        )
        return list(response.embeddings[0].values)

    async def seed_initial_knowledge(self, user_id: str = DEFAULT_USER_ID) -> str:
        existing = await self.collection.count_documents({"user_id": user_id})
        if existing > 0:
            print(f"🌱 [Vector RAG] Knowledge base already seeded for {user_id} ({existing} docs).")
            return f"Knowledge base already seeded ({existing} documents)."

        mock_data = [
            {
                "user_id": user_id,
                "category": "recipe",
                "title": "Low-Sugar Matcha Chiffon Cake",
                "content": (
                    "Peggy's favorite low-carb recipe: Substitute sugar with Allulose, "
                    "use high-grade ceremonial matcha. Mental cost reduction: -4."
                ),
            },
            {
                "user_id": user_id,
                "category": "walk",
                "title": "SLU Hydrotherapy Walk Route",
                "content": (
                    "A beautiful 15-minute walk starting from South Lake Union toward the wooden docks. "
                    "High negative ions help reduce interview anxiety."
                ),
            },
            {
                "user_id": user_id,
                "category": "recovery",
                "title": "The Golden Purr Frequency",
                "content": (
                    "How to pet Lulu and Gray: Target the base of the ears and under the chin gently. "
                    "Triggers immediate oxytocin release and maximum battery impact (+6)."
                ),
            },
        ]

        print("🌱 [Vector RAG] Seeding Vector Knowledge Base into MongoDB Atlas...")
        for item in mock_data:
            combined_text = f"{item['title']}: {item['content']}"
            item["embedding"] = self._get_embedding(combined_text)
            item["created_at"] = datetime.datetime.now(datetime.timezone.utc)
            await self.collection.insert_one(item)

        print("✅ [Vector RAG] Seeding completed!")
        return "Seeding completed."

    async def search_health_knowledge_base(
        self,
        query: str,
        limit: int = 2,
        user_id: str = DEFAULT_USER_ID,
    ) -> list[dict[str, Any]]:
        """
        [Day 17 MCP Tool] Executes Atlas $vectorSearch for semantic wellness matches.
        """
        try:
            print(f"🔍 [Vector RAG] Searching knowledge base for: '{query}' (limit={limit})")
            query_vector = self._get_embedding(query)

            pipeline = [
                {
                    "$vectorSearch": {
                        "index": VECTOR_INDEX_NAME,
                        "path": "embedding",
                        "queryVector": query_vector,
                        "numCandidates": max(limit * 5, 10),
                        "limit": limit,
                        "filter": {"user_id": {"$eq": user_id}},
                    }
                },
                {
                    "$project": {
                        "_id": 0,
                        "embedding": 0,
                        "title": 1,
                        "content": 1,
                        "category": 1,
                        "user_id": 1,
                        "score": {"$meta": "vectorSearchScore"},
                    }
                },
            ]

            cursor = self.collection.aggregate(pipeline)
            results = await cursor.to_list(length=limit)
            print(f"🔍 [Vector RAG] Retrieved {len(results)} semantic match(es).")
            return results
        except Exception as error:
            print(f"❌ [Vector RAG] Vector search failed: {error}")
            return [{"status": "error", "message": f"Vector search failed: {error}"}]

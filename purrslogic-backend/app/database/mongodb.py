import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise RuntimeError("MONGODB_URI is not set")
        _client = AsyncIOMotorClient(uri)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    return get_client().get_default_database()


async def close_client() -> None:
    global _client
    if _client is not None:
        _client.close()
        _client = None

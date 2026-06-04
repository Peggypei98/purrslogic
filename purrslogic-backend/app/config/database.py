import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# # Load environment variable, fallback to local MongoDB if not found (default: mongodb://localhost:27017)
MONGO_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")

# Initialize asynchronous MongoDB client 
client = AsyncIOMotorClient(MONGO_URL)

# Specify and export the dedicated database instance (default: purrslogic)
db = client.purrslogic
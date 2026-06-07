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

# 🟢 [Purrslogic Database Radar] Check where we are actually connecting
if "localhost" in MONGO_URL:
    print("⚠️ [Database Radar] Missing cloud environment variable! Falling back to LOCAL Mac MongoDB.")
else:
    # Safely extract host for logging without exposing passwords
    try:
        host_info = MONGO_URL.split("@")[-1].split("/")[0]
        print(f"☁️ [Database Radar] Successfully connecting to MONGODB ATLAS CLOUD: {host_info}")
    except Exception:
        print("☁️ [Database Radar] Connecting to Cloud MongoDB Atlas.")
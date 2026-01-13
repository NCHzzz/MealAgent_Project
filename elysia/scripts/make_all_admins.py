import asyncio
import os
import sys
from pathlib import Path

# Add the project root to sys.path to allow importing from elysia
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from elysia.util.client import ClientManager
from elysia.api.core.log import logger
from dotenv import load_dotenv

async def make_all_admins():
    """
    Script to update all existing users in the UserProfile collection to have the 'admin' role.
    """
    # Load environment variables
    load_dotenv(override=True)
    
    print("Connecting to Weaviate...")
    try:
        client_manager = ClientManager(logger=logger)
        
        async with client_manager.connect_to_async_client() as client:
            collection = client.collections.get("UserProfile")
            
            print("Fetching users and updating roles...")
            count = 0
            updated_count = 0
            
            # Use iterator to process all users
            async for obj in collection.iterator():
                count += 1
                email = obj.properties.get("email", "Unknown")
                current_role = obj.properties.get("role", "user")
                
                if current_role != "admin":
                    print(f"Updating user {email}: {current_role} -> admin")
                    await collection.data.update(
                        uuid=obj.uuid,
                        properties={"role": "admin"}
                    )
                    updated_count += 1
                else:
                    print(f"User {email} is already an admin.")
            
            print(f"\nFinished processing {count} users.")
            print(f"Updated {updated_count} users to admin role.")
            
    except Exception as e:
        print(f"Error: {e}")
        logger.exception("Failed to update user roles")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(make_all_admins())

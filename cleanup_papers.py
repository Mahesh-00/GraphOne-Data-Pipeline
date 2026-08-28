import asyncio

from src.storage.db import Storage


async def main():
    storage = Storage()

    try:
        await storage.init_models()

        result = await storage.delete_duplicate_research_papers()

        print()
        print("=== ARXIV DUPLICATE CLEANUP ===")
        print("Before :", result["before"])
        print("After  :", result["after"])
        print("Deleted:", result["deleted"])
        print("===============================")
        print()

    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())

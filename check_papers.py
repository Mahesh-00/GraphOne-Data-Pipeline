import asyncio

from src.storage.db import Storage


async def main():
    storage = Storage()

    try:
        await storage.init_models()

        papers = await storage.fetch_all("RESEARCH_PAPER")

        print()
        print("TOTAL PAPERS:", len(papers))
        print()

        for i, paper in enumerate(papers[-20:], start=1):
            print(f"--- Paper {i} ---")
            print("Title:", paper.get("title"))
            print("Authors:", paper.get("authors"))
            print("Paper URL:", paper.get("paper_url"))
            print("GitHub URL:", paper.get("github_url"))
            print("GitHub Stars:", paper.get("github_stars"))
            print("Published:", paper.get("published_date"))
            print()

    finally:
        await storage.close()


if __name__ == "__main__":
    asyncio.run(main())
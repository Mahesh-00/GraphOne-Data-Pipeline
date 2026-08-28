import asyncio
import ssl

import aiohttp
import certifi


async def main():
    url = (
        "https://export.arxiv.org/api/query"
        "?search_query=cat:cs.AI&max_results=1"
    )

    ssl_context = ssl.create_default_context(
        cafile=certifi.where()
    )

    connector = aiohttp.TCPConnector(
        ssl=ssl_context
    )

    async with aiohttp.ClientSession(
        connector=connector
    ) as session:

        async with session.get(url) as response:
            print("STATUS:", response.status)

            text = await response.text()

            print("RESPONSE LENGTH:", len(text))
            print(text[:500])


asyncio.run(main())
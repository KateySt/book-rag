import asyncio
import logging

from consumer import relay
from vercel.queue import poll_and_handle


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    await poll_and_handle(relay, interval=1.0, limit=1)


if __name__ == "__main__":
    asyncio.run(main())

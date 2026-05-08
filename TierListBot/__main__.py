from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from TierListBot.bot import run_bot
from TierListBot.config import load_settings


def main() -> None:
    load_dotenv()
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()

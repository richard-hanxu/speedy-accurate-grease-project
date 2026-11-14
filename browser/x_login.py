
import asyncio
from pathlib import Path
import zendriver as zd

PROFILE_DIR = Path.home() / ".zendriver_x_profile"

async def main():
    browser = await zd.start(
        headless=False,
        user_data_dir=str(PROFILE_DIR),
    )

    try:
        tab = await browser.get("https://x.com/i/flow/login")

        print("Chrome opened.")
        print("Log into X manually in the browser.")
        print("Complete any 2FA verification.")

        await asyncio.to_thread(
            input,
            "Press Enter AFTER login is complete..."
        )

        print("Current URL:", await tab.evaluate("location.href"))

    finally:
        await browser.stop()

if __name__ == "__main__":
    asyncio.run(main())

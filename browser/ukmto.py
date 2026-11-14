
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import zendriver as zd

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.cwd() / "gmail_app.env")

URL = "https://www.ukmto.org/recent-incidents"
OUTPUT_DIR = Path("reports")


async def get_text(tab):
    """Extract the visible text from the page."""
    return await tab.evaluate("document.body.innerText")


async def get_links(tab):
    """Return links on the current page."""
    return await tab.evaluate("""
        [...document.querySelectorAll('a[href]')]
            .map(a => ({
                text: a.innerText.trim(),
                url: a.href
            }))
            .filter(a => a.text && a.url.startsWith('http'))
    """)


async def show_links(tab):
    links = await get_links(tab)

    for i, link in enumerate(links):
        print(f"{i}: {link['text'][:65]}")
        print(f"    {link['url']}")

    return links


async def save_report(tab):
    """Save current page text and metadata locally."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(
        "%Y%m%d_%H%M%S"
    )

    text = await get_text(tab)
    url = await tab.evaluate("location.href")
    title = await tab.evaluate("document.title")

    path = OUTPUT_DIR / f"ukmto_{timestamp}.json"

    path.write_text(
        json.dumps(
            {
                "timestamp_utc": timestamp,
                "url": url,
                "title": title,
                "text": text,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"Saved to {path}")


async def main():
    browser = await zd.start(
        headless=True,
        browser_executable_path="/usr/bin/google-chrome",
        browser_args=[
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--window-size=1920,1080",
        ],
    )

    try:
        tab = await browser.get(URL)

        print("Opened UKMTO in Chrome.")
        print("Complete any browser verification manually.")

        while True:
            print("""
Commands:
  text           Show visible page text
  links          List available links
  go <number>    Navigate to a numbered link
  click <css>    Click an element by CSS selector
  open <url>     Open another URL
  save           Save page data as JSON
  screenshot     Save screenshot
  quit           Exit
""")

            command = (await asyncio.to_thread(
                input, "UKMTO> "
            )).strip()

            try:
                if command == "quit":
                    break

                elif command == "text":
                    text = await get_text(tab)
                    print(text[:12000])

                elif command == "links":
                    await show_links(tab)

                elif command.startswith("go "):
                    index = int(command[3:].strip())
                    links = await get_links(tab)
                    tab = await browser.get(links[index]["url"])
                    print("Opened:", links[index]["url"])

                elif command.startswith("click "):
                    selector = command[6:].strip()
                    element = await tab.select(selector)
                    if element is None:
                        print("Element not found")
                    else:
                        await element.click()
                        await asyncio.sleep(2)
                        print("Clicked:", selector)

                elif command.startswith("open "):
                    url = command[5:].strip()
                    tab = await browser.get(url)

                elif command == "save":
                    await save_report(tab)

                elif command == "screenshot":
                    await tab.save_screenshot("ukmto.png")
                    print("Saved ukmto.png")

                else:
                    print("Unknown command")

            except Exception as exc:
                print("Error:", exc)

    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())


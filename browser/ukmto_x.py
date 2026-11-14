
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import zendriver as zd

URL = "https://x.com/UK_MTO"
LIMIT = 1500
OUTPUT_FILE = Path("ukmto_x_posts.json")
ET = ZoneInfo("America/New_York")

# Twitter/X Snowflake epoch in milliseconds
TWITTER_EPOCH_MS = 1288834974657


def get_post_timestamp(post_id):
    """Decode an X post ID into its creation timestamp."""
    timestamp_ms = (int(post_id) >> 22) + TWITTER_EPOCH_MS

    dt = datetime.fromtimestamp(
        timestamp_ms / 1000,
        tz=timezone.utc
    )

    return {
        "timestamp_utc": dt.isoformat(timespec="milliseconds"),
        "timestamp_et": dt.astimezone(ET).strftime(
            "%Y-%m-%d %H:%M:%S.%f %Z"
        )[:-0] if False else dt.astimezone(ET).isoformat(
            timespec="milliseconds"
        ),
    }


async def extract_posts(tab):
    """Extract posts using the current X article structure."""
    return await tab.evaluate("""
        (() => {
            const articles = [
                ...document.querySelectorAll('article')
            ];

            const posts = [];

            for (const article of articles) {
                const links = [
                    ...article.querySelectorAll('a[href]')
                ];

                // Find a permalink belonging to UKMTO.
                // Exclude links to images and videos.
                const postLink = links.find(a =>
                    /^\\/UK_MTO\\/status\\/\\d+\\/?$/i.test(
                        new URL(a.href).pathname
                    )
                );

                if (!postLink) continue;

                const match = postLink.pathname.match(
                    /\\/status\\/(\\d+)/
                );

                if (!match) continue;

                const postId = match[1];
                const text = article.innerText.trim();

                posts.push({
                    id: postId,
                    url: `https://x.com/UK_MTO/status/${postId}`,
                    text: text,
                    links: links
                        .map(a => a.href)
                        .filter(href =>
                            !href.includes('/status/') &&
                            !href.includes('/hashtag/')
                        )
                });
            }

            return posts;
        })()
    """)


async def main():
    print("Starting Chrome...", flush=True)

    PROFILE_DIR = Path.home() / ".zendriver_x_profile"

    # browser = await zd.start(
    #     headless=True,
    #     user_data_dir=str(PROFILE_DIR),
    #     browser_executable_path="/usr/bin/google-chrome",
    #     browser_args=[
    #         "--disable-dev-shm-usage",
    #         "--window-size=1920,1080",
    #     ],
    # )
    
    browser = await zd.start(
        headless=False,
        user_data_dir=str(PROFILE_DIR),
        browser_executable_path=(
            "/Applications/Google Chrome.app/"
            "Contents/MacOS/Google Chrome"
        ),
        browser_args=[
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
        ],
    )

    try:
        tab = await browser.get(URL)
        print("Opened:", URL, flush=True)

        await asyncio.sleep(5)

        print("Page URL:", await tab.evaluate("location.href"))

        print("Visible posts:", await tab.evaluate("""
            document.querySelectorAll('article').length
        """))

        print("Page preview:", (
            await tab.evaluate("document.body.innerText")
        )[:500])

        
        collected = {}
        scrolls_without_new_posts = 0
        MAX_STALLED_SCROLLS = 10
        total_scrolls = 0

        while len(collected) < LIMIT:
            posts = await extract_posts(tab)

            previous_count = len(collected)

            for post in posts:
                if post["id"] not in collected:
                    post.update(get_post_timestamp(post["id"]))
                    collected[post["id"]] = post

            new_count = len(collected) - previous_count

            if new_count > 0:
                # Reset whenever new posts are discovered
                scrolls_without_new_posts = 0
                print(
                    f"Found {new_count} new posts! "
                    f"Total: {len(collected)}/{LIMIT}. "
                    f"Stall counter reset.",
                    flush=True
                )
            else:
                scrolls_without_new_posts += 1
                print(
                    f"No new posts. "
                    f"Stalled: {scrolls_without_new_posts}/{MAX_STALLED_SCROLLS}",
                    flush=True
                )

            if len(collected) >= LIMIT:
                print(f"Reached limit of {LIMIT} posts.")
                break

            if scrolls_without_new_posts >= MAX_STALLED_SCROLLS:
                print(
                    f"No new posts after {MAX_STALLED_SCROLLS} "
                    "consecutive attempts. Exiting early."
                )
                break

            scroll_info = await tab.evaluate("""
                (() => {
                    const articles = [...document.querySelectorAll('article')];

                    if (!articles.length) {
                        return {error: 'No articles found'};
                    }

                    const last = articles[articles.length - 1];

                    last.scrollIntoView({
                        behavior: 'instant',
                        block: 'end'
                    });

                    let node = last.parentElement;

                    while (node && node !== document.body) {
                        const style = getComputedStyle(node);

                        if (
                            /(auto|scroll)/.test(style.overflowY) &&
                            node.scrollHeight > node.clientHeight
                        ) {
                            node.scrollBy({
                                top: node.clientHeight * 0.8,
                                behavior: 'instant'
                            });

                            return {
                                scrollTarget: node.tagName,
                                scrollTop: node.scrollTop,
                                scrollHeight: node.scrollHeight,
                                clientHeight: node.clientHeight
                            };
                        }

                        node = node.parentElement;
                    }

                    window.scrollBy(0, window.innerHeight * 0.8);

                    return {
                        scrollTarget: 'window',
                        scrollY: window.scrollY,
                        scrollHeight: document.documentElement.scrollHeight,
                        innerHeight: window.innerHeight
                    };
                })()
            """)

            total_scrolls += 1

            print(
                f"Scroll #{total_scrolls}: "
                f"{len(collected)} unique posts. "
                f"Scroll info: {scroll_info}",
                flush=True
            )

            await asyncio.sleep(2)
            
        diagnostics = await tab.evaluate("""
            (() => ({
                articles: document.querySelectorAll('article').length,
                bottomText: document.body.innerText.slice(-1500),
                scrollY: window.scrollY,
                maxScroll: document.documentElement.scrollHeight
                        - window.innerHeight,
                loginLinks: [...document.querySelectorAll('a')]
                    .filter(a => /log in|sign up/i.test(a.innerText))
                    .map(a => ({
                        text: a.innerText,
                        href: a.href
                    }))
            }))()
        """)

        print(json.dumps(diagnostics, indent=2))

        results = sorted(
            collected.values(),
            key=lambda p: int(p["id"]),
            reverse=True
        )[:LIMIT]

        OUTPUT_FILE.write_text(
            json.dumps(
                results,
                indent=2,
                ensure_ascii=False
            ),
            encoding="utf-8"
        )

        print(f"\\nCollected {len(results)} posts\\n")

        for i, post in enumerate(results, 1):
            print("=" * 70)
            print(f"POST {i}")
            print("Posted (ET):", post["timestamp_et"])
            print("Posted (UTC):", post["timestamp_utc"])
            print("URL:", post["url"])
            print("Text:", post["text"])
            print()

        print(f"Saved to {OUTPUT_FILE}")

    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())

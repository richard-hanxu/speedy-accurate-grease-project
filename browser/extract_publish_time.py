
import asyncio
import json
import zendriver as zd

URL = "https://www.ukmto.org/recent-incidents"


async def main():
    browser = await zd.start(
        headless=True,
        browser_executable_path="/usr/bin/google-chrome",
        browser_args=[
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
        ],
    )

    try:
        print("Loading UKMTO...", flush=True)
        tab = await browser.get(URL)

        # Wait for incident records to populate.
        # UKMTO may initially display "0 reports".
        for attempt in range(30):
            text = await tab.evaluate(
                "document.body?.innerText || ''"
            )

            if "UKMTO #204" in text or (
                "Recent Incidents" in text
                and "0 reports" not in text
                and "UKMTO #" in text
            ):
                break

            await asyncio.sleep(1)

        print("Page loaded. Inspecting metadata...\n")

        # 1. Find elements containing time metadata
        times = await tab.evaluate("""
            [...document.querySelectorAll(
                'time, [datetime], [data-date], [data-created], [data-published]'
            )].map(el => ({
                text: el.innerText,
                html: el.outerHTML.slice(0, 1000)
            }))
        """)

        print("=== TIME ELEMENTS ===")
        print(json.dumps(times, indent=2))

        # 2. Inspect HTML around incident #204
        incident_html = await tab.evaluate("""
            (() => {
                const el = [...document.querySelectorAll('*')]
                    .find(e =>
                        e.children.length === 0 &&
                        /UKMTO #204/.test(e.textContent)
                    );

                return el?.parentElement?.parentElement
                    ?.outerHTML.slice(0, 8000) ?? null;
            })()
        """)

        print("\n=== INCIDENT HTML ===")
        print(incident_html)

        # 3. Inspect potentially relevant network requests
        resources = await tab.evaluate("""
            performance.getEntriesByType('resource')
                .filter(r =>
                    /api|incident|report|graphql|json/i.test(r.name)
                )
                .map(r => ({
                    url: r.name,
                    type: r.initiatorType
                }))
        """)

        print("\n=== POSSIBLE API ENDPOINTS ===")
        print(json.dumps(resources, indent=2))

    finally:
        await browser.stop()


if __name__ == "__main__":
    asyncio.run(main())

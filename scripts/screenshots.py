"""Drive the running app with a headless browser and save screenshots to docs/img/.

    python scripts/screenshots.py [--base http://localhost:5173] [--date 2026-09-25]

Requires ``pip install playwright && python -m playwright install chromium`` and the
backend + frontend running.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:5173")
    parser.add_argument("--date", default="2026-09-25")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        page = phone.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(args.base)
        page.get_by_label("From").fill("Stuttgart Hbf")
        page.get_by_role("option").first.click()
        page.get_by_label("Leave after").fill("20:00")
        page.get_by_label("Date").fill(args.date)
        page.screenshot(path=OUT / "home.png", full_page=True)
        page.get_by_role("button", name="Check my way home").click()
        page.wait_for_selector(".journey-card", timeout=60000)
        page.screenshot(path=OUT / "home_check.png", full_page=True)
        page.locator(".journey-card").first.get_by_role("button", name="Show map").click()
        page.wait_for_selector(".leaflet-tile-loaded", state="attached", timeout=20000)
        page.wait_for_timeout(800)
        page.locator(".journey-card").first.screenshot(path=OUT / "journey_card.png")

        page.goto(f"{args.base}/accuracy")
        page.wait_for_selector("svg", timeout=20000)
        page.screenshot(path=OUT / "accuracy.png", full_page=True)

        desktop = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        dpage = desktop.new_page()
        dpage.goto(f"{args.base}/check?from=Konstanz%20Bahnhof&to=Villingen%20Bahnhof%2FZOB&after=20:00"
                   f"&date={args.date}&regional=1")
        dpage.wait_for_selector(".journey-card", timeout=60000)
        dpage.screenshot(path=OUT / "home_check_dark.png", full_page=True)

        # Horizontal overflow check at phone width.
        for path in ("/", "/deadline", "/accuracy", "/privacy", "/login"):
            page.goto(f"{args.base}{path}")
            page.wait_for_timeout(500)
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            if overflow:
                errors.append(f"horizontal overflow on {path}")
        browser.close()

    print("screenshots written to", OUT)
    if errors:
        print("problems:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    main()

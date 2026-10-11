"""Screenshot a page with headless Chrome (Playwright). Full page; for Streamlit, expands the app height first.
python screenshot.py [url] [out.png] [--scroll-to "CSS or text"]"""
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501/"
out = sys.argv[2] if len(sys.argv) > 2 else "dashboard.png"
section = sys.argv[3] if len(sys.argv) > 3 else None
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(url, wait_until="domcontentloaded", timeout=120000)
    pg.wait_for_timeout(2500)
    if ":85" in url:
        pg.wait_for_selector("text=All comments", timeout=120000)
        pg.wait_for_timeout(3000)
        h = pg.evaluate("() => { const m = document.querySelector('[data-testid=stMain]') || document.querySelector('section.main'); "
                        "const c = m && (m.querySelector('[data-testid=stMainBlockContainer]') || m.firstElementChild); return c ? c.scrollHeight + 120 : 3000 }")
        pg.set_viewport_size({"width": 1440, "height": int(min(h, 16000))})
        pg.wait_for_timeout(2500)
    if section:
        el = pg.locator(f"text={section}").first
        box = el.bounding_box()
        y = int(box["y"]) - 20 if box else 0
        pg.screenshot(path=out, clip={"x": 0, "y": y, "width": 1440, "height": 1700}, full_page=True)
    else:
        pg.screenshot(path=out, full_page=True)
    b.close()
print("wrote", out)

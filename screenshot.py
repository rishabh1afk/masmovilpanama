"""Screenshot the live dashboard (main view) with headless Chrome via Playwright.
python screenshot.py [url] [out.png]"""
import sys, asyncio
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8501/"
out = sys.argv[2] if len(sys.argv) > 2 else "dashboard.png"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1600, "height": 2000}, device_scale_factor=1)
    pg.goto(url, wait_until="networkidle", timeout=120000)
    if "8501" in url:
        pg.wait_for_selector("div.js-plotly-plot", timeout=120000)
        pg.wait_for_timeout(4000)
        # expand the Streamlit main container so the full page is captured
    else:
        pg.wait_for_timeout(3000)
    pg.screenshot(path=out, full_page=True)
    b.close()
print("wrote", out)

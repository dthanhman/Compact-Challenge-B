import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://localhost:8599"
OUT = Path("D:/AGENTIC/BT_Buoi7/Chanllenge_B/docs/figures")
TABS = {"Context inspector": "ui_inspector", "Checkpoint": "ui_checkpoint", "B1 Experiments": "ui_b1",
        "B2 Code Mode": "ui_b2", "Simulation": "ui_simulation"}

for _ in range(60):  # chờ server sẵn sàng
    try:
        urllib.request.urlopen(URL + "/_stcore/health", timeout=2)
        break
    except Exception:
        time.sleep(1)
else:
    sys.exit("server not ready")

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=1)
    page.goto(URL)
    page.get_by_role("tab").first.wait_for(timeout=120_000)
    time.sleep(4)
    for label, name in TABS.items():
        page.get_by_role("tab", name=label).click()
        time.sleep(4)
        if label == "Context inspector":  # chọn run có compaction để thấy bảng trước/sau
            page.locator('[data-testid="stSelectbox"]').filter(has_text="Nguồn").locator("input").click()
            page.get_by_role("option", name="structured-t60-1", exact=False).first.click()
            time.sleep(4)
        page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
        print("saved", name)
    browser.close()

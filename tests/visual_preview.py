"""End-to-end desktop/mobile screenshots of the isolated local app, never production."""
import os
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "artifacts" / "site-preview"
DEST.mkdir(parents=True, exist_ok=True)
os.environ["SECRET_KEY"] = "e2e-testing-key-only-never-use-for-deployment"
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempfile.gettempdir()) / "gtech_browser_preview.sqlite")
os.environ["ADMIN_USER"] = "e2e-preview"
os.environ["ADMIN_PASS"] = "local-only-no-remote-access"
os.environ["CRM_LEAD_SYNC_ENABLED"] = "false"
os.environ["FLASK_DEBUG"] = "0"
os.environ["PORT"] = "5073"
# Enable the preview-only iframe gallery, but block all external requests in the browser.
os.environ["RAILWAY_ENVIRONMENT"] = "preview"
server = subprocess.Popen(
    ["python", "app.py"], cwd=ROOT, env=os.environ.copy(),
    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
)
try:
    for _ in range(50):
        try:
            with urlopen("http://127.0.0.1:5073/health", timeout=.6) as resp:
                if resp.status == 200: break
        except Exception:
            time.sleep(.25)
    else:
        raise AssertionError("Local preview server failed to start")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        for label, width, height in [("desktop",1440,900),("mobile",390,844)]:
            page=browser.new_page(viewport={"width":width,"height":height},device_scale_factor=1)
            page.route("**/drive.google.com/**",lambda route:route.abort())
            page.route("https://fonts.googleapis.com/**",lambda route:route.abort())
            errors=[]
            page.on("pageerror",lambda e:errors.append(str(e)))
            page.goto("http://127.0.0.1:5073/",wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            assert page.locator("h1").first.is_visible(), "Hero heading not visible"
            assert page.locator('.gtech-intro').count()==1, "Intro missing on first visit"
            page.wait_for_timeout(600)
            page.screenshot(path=str(DEST/f"{label}_intro.png"))
            # Record the actual particle shatter at three points, not a still mockup.
            page.wait_for_timeout(1350)
            page.screenshot(path=str(DEST/f"{label}_atom_break_1.png"))
            page.wait_for_timeout(530)
            page.screenshot(path=str(DEST/f"{label}_atom_break_2.png"))
            page.wait_for_timeout(430)
            page.screenshot(path=str(DEST/f"{label}_atom_break_3.png"))
            page.locator("#gtech-intro-skip").click()
            page.wait_for_timeout(720)
            assert page.locator(".gtech-intro").count()==0, "Intro not removed after skip"
            assert page.locator("#solucoes .service-card").count()==6, "Six offers not present"
            assert page.locator("#midias-reais iframe").count()==3, "Original videos not wired in preview"
            # Make all below-the-fold content visible in full-page screenshot.
            page.evaluate("document.querySelectorAll('.reveal').forEach(el=>el.classList.add('visible'))")
            page.screenshot(path=str(DEST/f"{label}_full.png"),full_page=True,animations="disabled",timeout=30000)
            overflow=page.evaluate("document.documentElement.scrollWidth-window.innerWidth")
            assert overflow<=3, f"Horizontal scroll overflow of {overflow}px on {label}"
            assert not errors, "Page JS errors: "+"; ".join(errors)
            print(f"PASS {label}: 6 services, 3 previews, intro, no overflow, no JS exceptions")
            page.close()
        browser.close()
finally:
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()

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
# Test the preview in isolation. External tracking and Drive media must not be required.
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
            # Trigger the close handler safely after the late shatter frames; the intro may already be fading.
            page.evaluate("document.querySelector(\'#gtech-intro-skip\')?.click()")
            page.wait_for_timeout(790)
            assert page.locator(".gtech-intro").count()==0, "Intro not removed after skip"
            assert page.locator("#solucoes .service-card").count()==6, "Six offers not present"
            assert page.locator("#projetos video").count()==4, "Four locally hosted project videos required"
            assert page.locator(".hero video#showcase-video").count()==1, "Belém Studio must feature in hero"
            assert page.locator("#video-belem-studio video source").get_attribute("src").endswith("/static/media/belem-studio-nfc.mp4")
            assert page.locator("iframe").count()==0, "External player must never be required"
            assert page.locator("fieldset.briefing-fields").get_attribute("disabled") is not None, "Preview fieldset must be disabled"
            assert page.locator("#quote-form input[name=nome]").is_disabled(), "Preview must not collect live personal data"
            assert page.locator("#cookie-notice").is_visible(), "Cookie consent choice missing"
            page.screenshot(path=str(DEST/f"{label}_cookies.png"))
            page.locator('[data-cookie-choice="essential"]').click()
            assert page.locator("#cookie-notice").is_hidden(), "Cookie consent was not dismissed"
            assert page.locator("#depoimentos .review-proof img").count()==2, "Two real feedback screenshots missing"
            assert page.locator(".intro-logo").count()==0, "Intro should be removed after skip"
            assert "🍔" not in page.locator("#projetos").inner_text(), "Generic burger mockup still present"
            # Verify the actual customer feedback screenshots were loaded, not blank boxes.
            images=page.locator("#depoimentos .review-proof img")
            page.wait_for_function("Array.from(document.querySelectorAll('#depoimentos .review-proof img')).every(img=>img.complete && img.naturalWidth>0)",timeout=10000)
            assert images.count()==2
            # Ensure images are decoded and actually painted in the viewport before full-page capture.
            page.evaluate("Promise.all(Array.from(document.querySelectorAll('#depoimentos .review-proof img')).map(img=>img.decode()))")
            page.locator("#depoimentos").scroll_into_view_if_needed()
            page.wait_for_timeout(250)
            page.screenshot(path=str(DEST/f"{label}_feedbacks.png"),animations="disabled")
            page.locator("#projetos").scroll_into_view_if_needed()
            page.wait_for_timeout(250)
            page.screenshot(path=str(DEST/f"{label}_portfolio.png"),animations="disabled")
            page.evaluate("document.querySelectorAll('.reveal').forEach(el=>el.classList.add('visible'))")
            page.screenshot(path=str(DEST/f"{label}_full.png"),full_page=True,animations="disabled",timeout=30000)
            mp4=page.request.get("http://127.0.0.1:5073/static/media/belem-studio-nfc.mp4")
            assert mp4.ok and "video/mp4" in mp4.headers.get("content-type",""), "Belém Studio video not playable from own server"
            assert mp4.body()[:4] != b"html", "MP4 endpoint served HTML instead of video"
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            assert page.locator(".gtech-intro").count()==1, "Opening must run again after refreshing"
            page.evaluate("document.querySelector('#gtech-intro-skip')?.click()")
            page.wait_for_timeout(700)
            assert page.locator("#cookie-notice").is_hidden(), "Cookie preference not respected after refresh"
            overflow=page.evaluate("document.documentElement.scrollWidth-window.innerWidth")
            assert overflow<=3, f"Horizontal scroll overflow of {overflow}px on {label}"
            assert not errors, "Page JS errors: "+"; ".join(errors)
            print(f"PASS {label}: 6 services, 4 self-hosted videos, cookies, repeatable intro, no overflow")
            page.close()
        browser.close()
finally:
    server.terminate()
    try:server.wait(timeout=5)
    except subprocess.TimeoutExpired:server.kill()

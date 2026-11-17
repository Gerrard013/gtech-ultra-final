"""Real Chromium form navigation, isolated DB and intercepted gateway; no real charge."""
import base64
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEST = ROOT / "artifacts" / "site-preview"
DEST.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory(prefix="gtech-checkout-journey-") as tmp:
    os.environ.update(DATABASE_URL="sqlite:///" + str(Path(tmp) / "test.sqlite"),
                      SECRET_KEY="isolated-checkout-journey-not-a-production-secret",
                      RAILWAY_ENVIRONMENT="", CRM_LEAD_SYNC_ENABLED="false", CRM_PAYMENT_SYNC_ENABLED="false")
    from app import app, db, CheckoutOrder
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    destination = "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=isolated-test-only"
    server = make_server("127.0.0.1", 0, app, threaded=True)
    origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch("app._checkout_enabled", return_value=True), \
             patch("app._create_mercadopago_preference", return_value=destination) as gateway, \
             patch("app._mp_request", side_effect=AssertionError("Remote payment API forbidden in this test")), \
             sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            for label, width, height, sku, cents in [("desktop",1440,900,"foto",1000),("mobile",390,844,"google",15000)]:
                page = browser.new_page(viewport={"width":width,"height":height})
                # CDP pauses each redirect hop. Playwright's route handler only
                # runs for the initial URL, which could let a 303 escape the mock.
                cdp = page.context.new_cdp_session(page)
                gateway_requests = []
                def intercept(event):
                    url = event["request"]["url"]
                    params = {"requestId":event["requestId"]}
                    if url.startswith(origin + "/"):
                        cdp.send("Fetch.continueRequest", params)
                    elif url == destination:
                        gateway_requests.append(event["request"]["method"])
                        cdp.send("Fetch.fulfillRequest", dict(params, responseCode=200,
                            responseHeaders=[{"name":"Content-Type","value":"text/html; charset=utf-8"}],
                            body=base64.b64encode(b"<h1>Isolated gateway reached</h1>").decode()))
                    else:
                        cdp.send("Fetch.failRequest", dict(params, errorReason="BlockedByClient"))
                cdp.on("Fetch.requestPaused", intercept)
                cdp.send("Fetch.enable", {"patterns":[{"urlPattern":"*","requestStage":"Request"}]})
                page.goto(origin + "/comprar/" + sku, wait_until="domcontentloaded")
                assert page.locator(".checkout-total strong").inner_text() == "R$ " + f"{cents/100:.2f}".replace(".",",")
                assert page.evaluate("document.documentElement.scrollWidth-window.innerWidth") <= 3
                page.screenshot(path=str(DEST / f"{label}_checkout_live_layout.png"),full_page=True)
                page.get_by_label("Seu nome completo").fill("Cliente de teste isolado")
                page.get_by_label("WhatsApp com DDD").fill("(91) 98273-6418")
                page.locator('input[name="consentimento"]').check()
                page.locator('input[name="termos"]').check()
                with page.expect_navigation(url=destination,timeout=10000):
                    page.get_by_role("button",name="Ir ao Mercado Pago").click()
                assert gateway_requests == ["GET"], "303 must navigate to hosted checkout exactly once"
                assert page.locator("h1").inner_text() == "Isolated gateway reached", "CSP blocked hosted checkout navigation"
                with app.app_context():
                    order = CheckoutOrder.query.filter_by(sku=sku).one()
                    assert order.total_cents == cents and order.status == "pending"
                print(f"PASS {label}: correct total, real browser 303 to intercepted Mercado Pago, no real charge")
                page.close()
            assert gateway.call_count == 2
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=5)
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

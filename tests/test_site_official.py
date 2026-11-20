"""Smoke tests for the official G Tech storefront. No remote payment or CRM calls."""
import base64
import os
import re
import tempfile
import unittest
from unittest.mock import patch

# Tests MUST use isolated SQLite; never point at the Railway production DB.
_TEST_DB = tempfile.NamedTemporaryFile(prefix="gtech_site_test_", suffix=".sqlite3", delete=False)
_TEST_DB.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB.name
os.environ["SECRET_KEY"] = "gtech-ci-test-only-secret-never-use-in-production"
os.environ["ADMIN_USER"] = "ci-admin"
os.environ["ADMIN_PASS"] = "ci-password-for-tests-only"
os.environ["CRM_LEAD_SYNC_ENABLED"] = "false"
os.environ["CRM_PAYMENT_SYNC_ENABLED"] = "false"

from app import (app, db, Lead, ConsentEvidence, SERVICES, _lead_attempts, _lead_attempts_lock,
                 _admin_failed, _admin_failed_lock, normalize_mobile)


class OfficialSiteTests(unittest.TestCase):
    def setUp(self):
        assert "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]
        app.config["TESTING"] = True
        with _lead_attempts_lock:
            _lead_attempts.clear()
        with _admin_failed_lock:
            _admin_failed.clear()
        with app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        with app.app_context():
            db.session.remove()

    def csrf(self):
        self.client.get("/")
        with self.client.session_transaction() as sess:
            return sess["lead_csrf"]

    def checkout_nonce(self, page):
        match = re.search(r'name="checkout_intent" value="([^"]+)"', page.get_data(as_text=True))
        self.assertIsNotNone(match, "Checkout nonce missing")
        return match.group(1)

    def nfc_shipping(self):
        return {
            "nfc_delivery_region": "local", "nfc_cep": "66035000",
            "nfc_city": "Belém", "nfc_state": "PA",
            "nfc_street": "Rua das Flores", "nfc_number": "120",
            "nfc_neighborhood": "Nazaré", "nfc_complement": "Sala 2"
        }

    def lead_data(self, csrf=None):
        return {
            "csrf_token": csrf if csrf is not None else self.csrf(),
            "nome": "Cliente Exemplo",
            "whatsapp": "(91) 98273-6418",
            "negocio": "Loja de testes",
            "cidade": "Belém",
            "servico": "Placa NFC Personalizada",
            "prazo": "Em até 7 dias",
            "objetivo": "Quero integrar informações de contato com NFC.",
            "origem": "site_oficial_v2|instagram",
            "consentimento": "yes",
            "termos": "yes",
        }

    def test_home_renders_six_offers_and_contact(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(len(SERVICES), 6)
        self.assertIn("Plaquinha NFC", html)
        self.assertIn("Perfil da Empresa no Google", html)
        self.assertIn("5591986152222", html)
        self.assertIn('name="csrf_token"', html)
        self.assertIn('name="consentimento"', html)
        self.assertIn('name="termos"', html)
        self.assertIn("/termos", html)

    def test_home_boots_branded_opening_before_video_load(self):
        page = self.client.get("/")
        html = page.get_data(as_text=True)
        self.assertIn('id="gtech-intro-start"', html)
        self.assertIn('id="gtech-intro-template"', html)
        self.assertLess(html.index('id="gtech-intro-start"'), html.index('id="showcase-video"'))
        self.assertIn('id="gtech-intro-replay"', html)
        self.assertNotIn('id="showcase-video" class="scene-video belem-video" controls muted playsinline autoplay', html)
        self.assertIn("20261119-intro-first", html)
        self.assertIn('href="/comprar/nfc"', html)

    def test_contact_form_saves_local_lead_without_payment(self):
        data = self.lead_data()
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network used")):
            response = self.client.post("/lead", data=data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/obrigado"))
        with app.app_context():
            saved = Lead.query.one()
            self.assertEqual(saved.servico, "Placa NFC Personalizada")
            self.assertEqual(saved.whatsapp, "91982736418")
            self.assertEqual(saved.status, "novo")
            self.assertEqual(saved.origem, "site_oficial_v2|instagram")
            self.assertIn("Cidade: Belém", saved.mensagem)

    def test_rejects_invalid_phone(self):
        data = self.lead_data()
        data["whatsapp"] = "123"
        response = self.client.post("/lead", data=data)
        self.assertEqual(response.status_code, 422)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        html = response.get_data(as_text=True)
        self.assertIn('value="Cliente Exemplo"', html)
        self.assertIn('value="123"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('id="quote-phone-error"', html)
        self.assertIn('value="Loja de testes"', html)
        self.assertIn('value="Belém"', html)
        self.assertIn('value="yes" required checked', html)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)

    def test_rejects_obviously_generic_or_invalid_brazilian_numbers(self):
        self.assertEqual(normalize_mobile("+55 (91) 98273-6418"), "91982736418")
        for number in ["(91) 99999-9999", "(91) 91234-5678", "(00) 98273-6418",
                       "(91) 11111-1111", "1198765432", "00000000000",
                       "91900000000", "+55 91 99999-9999"]:
            self.assertIsNone(normalize_mobile(number), number)
            with _lead_attempts_lock:
                _lead_attempts.clear()
            payload = self.lead_data()
            payload["whatsapp"] = number
            response = self.client.post("/lead", data=payload)
            self.assertEqual(response.status_code, 422, number)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)

    def test_rate_limit_responds_without_storing_sixth_lead(self):
        payload = self.lead_data()
        for _ in range(5):
            response=self.client.post("/lead",data=payload)
            self.assertEqual(response.status_code,302)
        result=self.client.post("/lead",data=payload)
        self.assertEqual(result.status_code,429)
        with app.app_context():
            self.assertEqual(Lead.query.count(),5)

    def test_rejects_missing_consent(self):
        data = self.lead_data()
        del data["consentimento"]
        response = self.client.post("/lead", data=data)
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)

    def test_rejects_missing_terms_without_storing_lead(self):
        data = self.lead_data()
        data.pop("termos")
        response = self.client.post("/lead", data=data)
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)
            self.assertEqual(ConsentEvidence.query.count(), 0)

    def test_expired_or_missing_csrf_is_safe_and_customer_friendly(self):
        for bad_token in ["", "stale-token-from-old-tab"]:
            payload = self.lead_data()
            payload["csrf_token"] = bad_token
            response = self.client.post("/lead", data=payload)
            self.assertEqual(response.status_code, 303)
            self.assertIn("#contato", response.location)
            page = self.client.get("/")
            self.assertIn("Sua sessão de segurança expirou", page.get_data(as_text=True))
            with app.app_context():
                self.assertEqual(Lead.query.count(), 0)
                self.assertEqual(ConsentEvidence.query.count(), 0)

    def test_fresh_security_token_repairs_expired_cookie_before_submit(self):
        original = self.csrf()
        with self.client.session_transaction() as sess:
            sess.pop("lead_csrf", None)
        token_response = self.client.get("/api/form-token")
        self.assertEqual(token_response.status_code, 200)
        self.assertIn("no-store", token_response.headers.get("Cache-Control", ""))
        self.assertIn("private", token_response.headers.get("Cache-Control", ""))
        token = token_response.json["csrf_token"]
        self.assertTrue(len(token) >= 30)
        self.assertNotEqual(token, original)
        payload = self.lead_data()
        payload["csrf_token"] = token
        with patch("urllib.request.urlopen", side_effect=AssertionError("Network used")):
            response = self.client.post("/lead", data=payload)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/obrigado"))
        with app.app_context():
            self.assertEqual(Lead.query.count(), 1)

    def test_honeypot_form_autofill_rejected_without_bad_request(self):
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn('name="form_guard_9"', page)
        self.assertNotIn('name="website"', page)
        for field in ["form_guard_9", "website"]:
            payload = self.lead_data()
            payload[field] = "auto-filled-example.invalid"
            response = self.client.post("/lead", data=payload)
            self.assertEqual(response.status_code, 303)
            self.assertIn("#contato", response.location)
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)

    def test_admin_requires_auth_and_csrf(self):
        self.assertEqual(self.client.get("/admin/leads").status_code, 401)
        key = base64.b64encode(b"ci-admin:ci-password-for-tests-only").decode()
        auth = {"Authorization": "Basic " + key}
        page = self.client.get("/admin/leads", headers=auth)
        self.assertEqual(page.status_code, 200)
        with app.app_context():
            lead = Lead(nome="Cliente Exemplo", whatsapp="91999991234",
                        negocio="Teste", servico="Site Profissional",
                        prazo="Em até 7 dias", objetivo="Site", origem="site")
            db.session.add(lead)
            db.session.commit()
            ident = lead.id
        page = self.client.get("/admin/leads", headers=auth)
        self.assertIn(b'admin_csrf', page.data)
        path = f"/admin/leads/{ident}/status"
        self.assertEqual(self.client.post(path, data={"status": "proposta"}, headers=auth).status_code, 400)
        with self.client.session_transaction() as sess:
            token = sess["admin_csrf"]
        self.assertEqual(self.client.post(path, data={"status": "proposta", "admin_csrf": token}, headers=auth).status_code, 302)

    def test_preview_does_not_collect_leads_or_get_indexed(self):
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "preview"}):
            page = self.client.get("/")
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.headers.get("X-Robots-Tag"), "noindex, nofollow, noarchive")
            self.assertIn(b'noindex,nofollow', page.data)
            self.assertNotIn(b'drive.google.com', page.data)
            self.assertIn(b'belem-studio-nfc.mp4', page.data)
            self.assertIn(b'cookie-notice', page.data)
            payload = self.lead_data()
            blocked = self.client.post("/lead", data=payload)
            self.assertEqual(blocked.status_code, 403)
            with app.app_context():
                self.assertEqual(Lead.query.count(), 0)


    def test_crm_sync_off_keeps_lead_pending(self):
        from app import sync_lead_to_crm, CrmDelivery
        with app.app_context():
            lead=Lead(nome="Cliente Teste",whatsapp="91982736418",negocio="Teste G Tech",
                      servico="Placa NFC Personalizada",prazo="Em até 7 dias",
                      objetivo="Demonstração de NFC para estabelecimento",origem="site_test")
            db.session.add(lead)
            db.session.commit()
            with patch.dict(os.environ,{"CRM_LEAD_SYNC_ENABLED":"false"}):
                with patch("urllib.request.urlopen",side_effect=AssertionError("No network while disabled")):
                    self.assertFalse(sync_lead_to_crm(lead,"Belém"))
            self.assertEqual(Lead.query.count(),1)
            self.assertEqual(db.session.get(CrmDelivery,lead.id).status,"pending")

    def test_signed_crm_payload_accepted_only_with_consent_and_idempotent(self):
        import io, json, hmac, hashlib
        from app import sync_lead_to_crm, CrmDelivery, ConsentEvidence, CRM_SITE_ENDPOINT
        secret="unit-test-only-secret-for-signed-site-handoff-2026"
        captured=[]
        class Response(io.BytesIO):
            status=201
            def __enter__(self):return self
            def __exit__(self,*_args):return False
        def fake_urlopen(req, timeout):
            self.assertEqual(req.full_url,CRM_SITE_ENDPOINT)
            self.assertEqual(timeout,5)
            self.assertEqual(req.get_method(),"POST")
            timestamp=req.headers["X-gtech-timestamp"]
            sig=req.headers["X-gtech-signature"]
            expect=hmac.new(secret.encode(),timestamp.encode()+b"."+req.data,hashlib.sha256).hexdigest()
            self.assertEqual(sig,"sha256="+expect)
            payload=json.loads(req.data)
            self.assertEqual(payload["name"],"Cliente Teste")
            self.assertEqual(payload["phone"],"5591982736418")
            self.assertEqual(payload["product"],"nfc")
            self.assertEqual(payload["city"],"Belém")
            self.assertEqual(payload["termsVersion"],"2026-11-16")
            self.assertEqual(payload["privacyVersion"],"2026-11-16")
            self.assertIs(payload["consent"],True)
            self.assertIs(payload["termsAccepted"],True)
            captured.append(payload)
            return Response(b'{"ok":true,"created":true}')
        with app.app_context():
            lead=Lead(nome="Cliente Teste",whatsapp="91982736418",negocio="Loja de Testes",
                      servico="Placa NFC Personalizada",prazo="Em até 7 dias",
                      objetivo="Quero NFC para disponibilizar perfil de contato",origem="site")
            db.session.add(lead)
            db.session.flush()
            db.session.add(ConsentEvidence(lead_id=lead.id,purpose="budget",
                        privacy_version="2026-11-16",terms_version="2026-11-16"))
            db.session.commit()
            env={"CRM_LEAD_SYNC_ENABLED":"true","CRM_LEAD_CAPTURE_URL":CRM_SITE_ENDPOINT,
                 "GTECH_SITE_LEAD_SECRET":secret}
            with patch.dict(os.environ,env):
                with patch("urllib.request.urlopen",side_effect=fake_urlopen):
                    self.assertTrue(sync_lead_to_crm(lead,"Belém"))
                    self.assertTrue(sync_lead_to_crm(lead,"Belém"))
            self.assertEqual(len(captured),1)
            delivery=db.session.get(CrmDelivery,lead.id)
            self.assertEqual(delivery.status,"delivered")
            self.assertEqual(delivery.attempts,1)

    def test_crm_failure_and_unsigned_lead_stay_local(self):
        from app import sync_lead_to_crm, CrmDelivery, ConsentEvidence, CRM_SITE_ENDPOINT
        secret="unit-test-only-secret-for-signed-site-handoff-2026"
        with app.app_context():
            lead=Lead(nome="Cliente Teste",whatsapp="91982736418",negocio="Empresa Teste",
                      servico="Site Profissional",prazo="Estou pesquisando",
                      objetivo="Preciso de uma vitrine digital com agendamentos",origem="site")
            db.session.add(lead)
            db.session.commit()
            env={"CRM_LEAD_SYNC_ENABLED":"true","CRM_LEAD_CAPTURE_URL":CRM_SITE_ENDPOINT,
                 "GTECH_SITE_LEAD_SECRET":secret}
            with patch.dict(os.environ,env):
                with patch("urllib.request.urlopen",side_effect=AssertionError("No consent: no network")):
                    self.assertFalse(sync_lead_to_crm(lead,"Belém"))
                db.session.add(ConsentEvidence(lead_id=lead.id,purpose="budget",
                            privacy_version="2026-11-16",terms_version="2026-11-16"))
                db.session.commit()
                with patch("urllib.request.urlopen",side_effect=TimeoutError("Synthetic network timeout")):
                    self.assertFalse(sync_lead_to_crm(lead,"Belém"))
            self.assertIsNotNone(db.session.get(Lead,lead.id))
            delivery=db.session.get(CrmDelivery,lead.id)
            self.assertEqual(delivery.status,"pending")
            self.assertEqual(delivery.attempts,1)

    def test_checkout_invalid_phone_preserves_name_and_consent(self):
        # Unit-test the validation branch without activating real payments.
        with patch("app._checkout_enabled", return_value=True):
            page = self.client.get("/comprar/google")
            self.assertEqual(page.status_code, 200)
            with self.client.session_transaction() as sess:
                csrf_token = sess["checkout_csrf"]
            result = self.client.post("/comprar/google", data={
                "csrf_token": csrf_token, "checkout_intent": self.checkout_nonce(page),
                "nome": "Maria da Silva", "whatsapp": "123",
                "consentimento": "yes", "termos": "yes",
            })
        self.assertEqual(result.status_code, 422)
        self.assertIn("no-store", result.headers.get("Cache-Control", ""))
        html = result.get_data(as_text=True)
        self.assertIn('value="Maria da Silva"', html)
        self.assertIn('value="123"', html)
        self.assertIn('id="checkout-phone-error"', html)
        self.assertIn('aria-invalid="true"', html)
        self.assertNotIn("mercadopago.com/checkout", result.headers.get("Location", ""))
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)



    def test_repeated_checkout_request_reuses_order_instead_of_charging_twice(self):
        from app import CheckoutOrder, CheckoutAttempt
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-idempotency",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-signed-webhook-only-12345",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "RAILWAY_ENVIRONMENT": "production",
        }
        sent = []
        def fake_gateway(path, data=None, **kwargs):
            if path == "/users/me":
                return {"id": 12345678}
            sent.append(data)
            return {"collector_id": 12345678,
                    "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=once"}
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/foto")
            with self.client.session_transaction() as sess:
                token = sess["checkout_csrf"]
            data = {"csrf_token": token, "checkout_intent": self.checkout_nonce(page),
                    "nome": "Cliente Exemplo", "whatsapp": "(91) 98273-6418",
                    "consentimento": "yes", "termos": "yes"}
            with patch("app._mp_request", side_effect=fake_gateway):
                first = self.client.post("/comprar/foto", data=data)
                second = self.client.post("/comprar/foto", data=data)
            self.assertEqual(first.status_code, 303)
            self.assertEqual(second.status_code, 303)
            self.assertEqual(first.location, second.location)
            self.assertEqual(len(sent), 1)
            with app.app_context():
                self.assertEqual(CheckoutOrder.query.count(), 1)
                self.assertEqual(CheckoutAttempt.query.count(), 1)

    def test_nfc_checkout_gateway_failure_restores_reserved_units(self):
        from app import NfcInventory, CheckoutOrder
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-gateway-failure",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-webhook-secret-123456789",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "GTECH_NFC_SALES_ENABLED": "true",
            "GTECH_NFC_INITIAL_STOCK": "5",
            "RAILWAY_ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                token = sess["checkout_csrf"]
            with patch("app._mp_request", side_effect=TimeoutError("gateway test")):
                response = self.client.post("/comprar/nfc", data={
                    "csrf_token": token, "checkout_intent": self.checkout_nonce(page),
                    "nome": "Comprador Teste", "whatsapp": "(91) 98273-6418",
                    "quantity": "2", "nfc_local_delivery": "yes", **self.nfc_shipping(),
                    "consentimento": "yes", "termos": "yes",
                })
        self.assertEqual(response.status_code, 302)
        with app.app_context():
            self.assertEqual(NfcInventory.query.one().available, 5)
            self.assertEqual(CheckoutOrder.query.one().status, "cancelled")

    def test_nfc_rejects_quantity_exceeding_remaining_stock(self):
        from app import NfcInventory, CheckoutOrder
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-stock-limit",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-webhook-secret-123456789",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "GTECH_NFC_SALES_ENABLED": "true",
            "GTECH_NFC_INITIAL_STOCK": "8",
            "RAILWAY_ENVIRONMENT": "production",
        }
        def mock_gateway(path, data=None, **kwargs):
            return ({"id": 12345678} if path == "/users/me" else
                    {"collector_id": 12345678,
                     "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=mock"})
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                token = sess["checkout_csrf"]
            payload = {"csrf_token": token, "checkout_intent": self.checkout_nonce(page),
                       "nome": "Comprador Teste", "whatsapp": "(91) 98273-6418",
                       "quantity": "7", "nfc_local_delivery": "yes", **self.nfc_shipping(),
                       "consentimento": "yes", "termos": "yes"}
            with patch("app._mp_request", side_effect=mock_gateway):
                first = self.client.post("/comprar/nfc", data=payload)
            self.assertEqual(first.status_code, 303)
            with app.app_context():
                self.assertEqual(NfcInventory.query.one().available, 1)
            second_page = self.client.get("/comprar/nfc")
            payload["checkout_intent"] = self.checkout_nonce(second_page)
            payload["quantity"] = "2"
            second = self.client.post("/comprar/nfc", data=payload)
            self.assertEqual(second.status_code, 422)
            self.assertIn("Estoque insuficiente", second.get_data(as_text=True))
            with app.app_context():
                self.assertEqual(NfcInventory.query.one().available, 1)
                self.assertEqual(CheckoutOrder.query.count(), 1)

    def test_nfc_crm_queue_reports_address_and_priority_before_payment(self):
        from app import CheckoutOrder, NfcDeliveryAddress
        import uuid
        with patch.dict(os.environ, {
            "GTECH_NFC_STOCK_SECRET": "test-private-inventory-secret-123456789",
            "GTECH_NFC_INITIAL_STOCK": "8"
        }):
            headers = {"X-GTech-NFC-Key": "test-private-inventory-secret-123456789"}
            with app.app_context():
                lead = Lead(nome="Cliente Teste", whatsapp="91982736418",
                            negocio="NFC", servico="Placa NFC Personalizada",
                            prazo="A definir", objetivo="Comprar NFC")
                db.session.add(lead)
                db.session.flush()
                order = CheckoutOrder(id=str(uuid.uuid4()),lead_id=lead.id,
                    sku="nfc",quantity=2,total_cents=15998,status="pending")
                db.session.add(order)
                db.session.flush()
                db.session.add(NfcDeliveryAddress(
                    order_id=order.id,cep="66035570",state="PA",city="Belém",
                    neighborhood="Condor",street="Rua Nova",number="356"))
                db.session.commit()
                order_id=order.id
            self.assertEqual(self.client.get("/internal/nfc/stock").status_code,403)
            result=self.client.get("/internal/nfc/stock",headers=headers)
            self.assertEqual(result.status_code,200)
            record=next(x for x in result.json["orders"] if x["id"]==order_id)
            self.assertEqual(record["address"]["street"],"Rua Nova")
            self.assertEqual(record["operationalPriority"],"waiting")
            self.assertEqual(record["fulfillment"]["status"],"not_started")
            attempt={"actionId":str(uuid.uuid4()),"actor":"Admin G Tech",
                     "status":"preparing", "note":"Iniciar separação do pedido"}
            before=self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=attempt)
            self.assertEqual(before.status_code,409)
            self.assertIn("Pagamento não confirmado",before.json["error"])
            with app.app_context():
                db.session.get(CheckoutOrder,order_id).status="approved"
                db.session.commit()
            result=self.client.get("/internal/nfc/stock",headers=headers)
            record=next(x for x in result.json["orders"] if x["id"]==order_id)
            self.assertEqual(record["operationalPriority"],"high")
            success=self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=attempt)
            self.assertEqual(success.status_code,200)
            replay=self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=attempt)
            self.assertTrue(replay.json["duplicate"])
            attempt2={"actionId":str(uuid.uuid4()),"actor":"Admin G Tech",
                     "status":"ready","priority":"urgent",
                     "note":"Pedido preparado para conferência"}
            self.assertEqual(self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=attempt2).status_code,200)
            invalid={"actionId":str(uuid.uuid4()),"actor":"Admin G Tech",
                     "status":"out_for_delivery",
                     "note":"Encaminhado para distribuição"}
            self.assertEqual(self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=invalid).status_code,422)
            valid={**invalid,"actionId":str(uuid.uuid4()),"deliveryReference":"Moto: operador 7"}
            self.assertEqual(self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json=valid).status_code,200)
            history=self.client.get("/internal/nfc/fulfillment/"+order_id,headers=headers)
            self.assertEqual(history.status_code,200)
            self.assertEqual(history.json["status"],"out_for_delivery")
            self.assertEqual(len(history.json["history"]),3)
            self.assertEqual(self.client.get("/internal/nfc/fulfillment/"+order_id).status_code,403)
            with app.app_context():
                from app import NfcFulfillmentEvent,NfcFulfillment
                self.assertEqual(NfcFulfillmentEvent.query.count(),3)
                self.assertEqual(NfcFulfillment.query.one().status,"out_for_delivery")
                db.session.get(CheckoutOrder,order_id).status="refunded"
                db.session.commit()
            locked=self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json={"actionId":str(uuid.uuid4()),"actor":"Admin G Tech",
                    "status":"delivered","note":"Entrega supostamente concluída",
                    "deliveryReference":"Moto: operador 7"})
            self.assertEqual(locked.status_code,409)
            hold=self.client.post("/internal/nfc/fulfillment/"+order_id,
                headers=headers,json={"actionId":str(uuid.uuid4()),"actor":"Admin G Tech",
                    "status":"on_hold","note":"Pagamento estornado; bloquear entrega"})
            self.assertEqual(hold.status_code,200)
            flagged=self.client.get("/internal/nfc/stock",headers=headers)
            record=next(x for x in flagged.json["orders"] if x["id"]==order_id)
            self.assertEqual(record["operationalPriority"],"urgent")

    def test_checkout_insert_respects_foreign_keys_on_sqlite(self):
        # SQLite normally disables FK checks, masking a production-only bug.
        # Enable them specifically for this test, mirroring PostgreSQL.
        from sqlalchemy import text
        from app import CheckoutOrder, CheckoutAttempt, NfcDeliveryAddress
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-ci-fake-secret",
            "MERCADOPAGO_WEBHOOK_SECRET": "ci-dummy-webhook-key-not-production",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "GTECH_NFC_SALES_ENABLED": "true",
            "GTECH_NFC_INITIAL_STOCK": "8",
            "RAILWAY_ENVIRONMENT": "production",
        }
        def fake_mp(path, data=None, **kwargs):
            return ({"id": 12345678} if path == "/users/me" else {
                "collector_id": 12345678,
                "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=fk-test"
            })
        with app.app_context():
            db.session.execute(text("PRAGMA foreign_keys=ON"))
            db.session.commit()
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                csrf = sess["checkout_csrf"]
            payload = {
                "csrf_token": csrf, "checkout_intent": self.checkout_nonce(page),
                "nome": "Teste Integridade", "whatsapp": "(91) 98273-6418",
                "quantity": "2", "nfc_local_delivery": "yes",
                "consentimento": "yes", "termos": "yes", **self.nfc_shipping(),
            }
            with patch("app._mp_request", side_effect=fake_mp):
                response = self.client.post("/comprar/nfc", data=payload)
            self.assertEqual(response.status_code, 303,
                             response.get_data(as_text=True)[:220])
        with app.app_context():
            self.assertEqual(CheckoutOrder.query.count(), 1)
            self.assertEqual(CheckoutAttempt.query.count(), 1)
            self.assertEqual(NfcDeliveryAddress.query.count(), 1)
            self.assertEqual(CheckoutOrder.query.one().quantity, 2)

    def test_nfc_quantity_and_price_are_server_authoritative(self):
        from app import CheckoutOrder, NfcInventory
        import json
        payloads = []
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-credential-not-valid",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-key-gtech-signed-webhook-only",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "GTECH_NFC_SALES_ENABLED": "true",
            "GTECH_NFC_INITIAL_STOCK": "8",
            "RAILWAY_ENVIRONMENT": "production",
        }
        def gateway(path, data=None, **kwargs):
            if path == "/users/me":
                return {"id": 12345678}
            self.assertEqual(path, "/checkout/preferences")
            payloads.append(data)
            return {"collector_id": 12345678,
                    "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=mock"}
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            self.assertEqual(page.status_code, 200)
            self.assertIn('name="quantity"', page.get_data(as_text=True))
            with self.client.session_transaction() as sess:
                csrf_token = sess["checkout_csrf"]
            for quantity in ("0", "-1", "9", "9999", "1.5", "abc"):
                # Each simulated visitor uses a fresh request-rate window.
                with _lead_attempts_lock:
                    _lead_attempts.clear()
                with self.subTest(quantity=quantity):
                    response = self.client.post("/comprar/nfc", data={
                        "csrf_token": csrf_token, "checkout_intent": self.checkout_nonce(page), "nome": "Cliente Exemplo",
                        "whatsapp": "(91) 98273-6418", "quantity": quantity,
                        "price": "1", "total_cents": "1",
                        "nfc_local_delivery": "yes", **self.nfc_shipping(), "consentimento": "yes", "termos": "yes",
                    })
                    self.assertEqual(response.status_code, 422)
                    self.assertIn('value="Cliente Exemplo"', response.get_data(as_text=True))
            with app.app_context():
                self.assertEqual(Lead.query.count(), 0)
                self.assertEqual(CheckoutOrder.query.count(), 0)
            with _lead_attempts_lock:
                _lead_attempts.clear()
            with patch("app._mp_request", side_effect=gateway):
                success = self.client.post("/comprar/nfc", data={
                    "csrf_token": csrf_token, "checkout_intent": self.checkout_nonce(page), "nome": "Cliente Exemplo",
                    "whatsapp": "(91) 98273-6418", "quantity": "3",
                    "price": "1", "total_cents": "1",
                    "nfc_local_delivery": "yes", **self.nfc_shipping(), "consentimento": "yes", "termos": "yes",
                })
            self.assertEqual(success.status_code, 303)
            self.assertEqual(len(payloads), 1)
            self.assertEqual(payloads[0]["items"][0]["quantity"], 3)
            self.assertEqual(payloads[0]["items"][0]["unit_price"], 79.99)
            with app.app_context():
                order = CheckoutOrder.query.one()
                self.assertEqual(order.total_cents, 23997)
                self.assertEqual(order.quantity, 3)
                self.assertEqual(NfcInventory.query.one().available, 5)
                from app import NfcDeliveryAddress
                self.assertEqual(NfcDeliveryAddress.query.one().cep, "66035000")
                self.assertEqual(NfcDeliveryAddress.query.one().city, "Belém")

    def test_private_stock_api_supports_domain_separated_existing_crm_secret(self):
        import hmac
        import hashlib
        master = "this-is-a-test-only-integration-secret-not-prod"
        key = hmac.new(master.encode(), b"gtech-nfc-inventory-v1", hashlib.sha256).hexdigest()
        with patch.dict(os.environ, {"GTECH_NFC_STOCK_SECRET": "",
                                     "GTECH_SITE_LEAD_SECRET": master,
                                     "GTECH_NFC_INITIAL_STOCK": "8"}):
            resp = self.client.get("/internal/nfc/stock", headers={"X-GTech-NFC-Key": key})
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json["available"], 8)
            self.assertEqual(self.client.get("/internal/nfc/stock",
                headers={"X-GTech-NFC-Key": master}).status_code, 403)

    def test_private_stock_api_blocks_unauthorized_and_audits_valid_adjustments(self):
        from app import NfcStockMovement
        import uuid
        with patch.dict(os.environ, {"GTECH_NFC_INITIAL_STOCK": "8",
                                     "GTECH_NFC_STOCK_SECRET": "x"*48}):
            self.assertEqual(self.client.get("/internal/nfc/stock").status_code, 403)
            headers = {"X-GTech-NFC-Key": "x"*48}
            initial = self.client.get("/internal/nfc/stock", headers=headers)
            self.assertEqual(initial.status_code, 200)
            self.assertEqual(initial.json["available"], 8)
            change = {"movementId": str(uuid.uuid4()), "delta": -2,
                      "reason": "Conferência física do estoque", "actor": "Gestor G Tech"}
            response = self.client.post("/internal/nfc/stock", json=change, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["available"], 6)
            duplicate = self.client.post("/internal/nfc/stock", json=change, headers=headers)
            self.assertEqual(duplicate.json.get("duplicate"), True)
            self.assertEqual(duplicate.json["available"], 6)
            denied = self.client.post("/internal/nfc/stock",
                json={**change, "movementId": str(uuid.uuid4()), "delta": -7}, headers=headers)
            self.assertEqual(denied.status_code, 409)
            with app.app_context():
                self.assertEqual(NfcStockMovement.query.count(), 1)

    def test_nfc_fallback_allows_quantity_inquiry_without_charging(self):
        from app import CheckoutOrder
        page = self.client.get("/comprar/nfc")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="nfc-quantity"', html)
        self.assertIn('id="nfc-whatsapp-order"', html)
        self.assertIn("Compra online de NFC ainda não liberada", html)
        self.assertNotIn('id="checkout-form"', html)
        with app.app_context():
            self.assertEqual(CheckoutOrder.query.count(), 0)

    def test_nfc_nationwide_request_cannot_charge_unquoted_freight(self):
        from app import CheckoutOrder
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-only",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-webhook-secret-123456789",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "true",
            "GTECH_NFC_SALES_ENABLED": "true",
            "GTECH_NFC_INITIAL_STOCK": "8", "RAILWAY_ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                csrf = sess["checkout_csrf"]
            payload = {
                "csrf_token": csrf, "checkout_intent": self.checkout_nonce(page),
                "nome": "Cliente Frete", "whatsapp": "(91) 98273-6418",
                "quantity": "2", "consentimento": "yes", "termos": "yes",
                "nfc_local_delivery": "yes", **self.nfc_shipping(),
                "nfc_delivery_region": "national", "nfc_city": "São Paulo",
                "nfc_state": "SP", "nfc_cep": "01310930"
            }
            with patch("app._mp_request", side_effect=AssertionError("Never charge without frete")):
                response = self.client.post("/comprar/nfc", data=payload)
            self.assertEqual(response.status_code, 422)
            self.assertIn("cotação prévia de frete", response.get_data(as_text=True))
            with app.app_context():
                self.assertEqual(CheckoutOrder.query.count(), 0)

    def test_nfc_local_missing_address_preserves_form_without_order(self):
        with patch.dict(os.environ, {
            "GTECH_NFC_SALES_ENABLED": "true", "GTECH_NFC_INITIAL_STOCK": "8"
        }), patch("app._checkout_enabled", return_value=True), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                csrf = sess["checkout_csrf"]
            result = self.client.post("/comprar/nfc", data={
                "csrf_token": csrf, "checkout_intent": self.checkout_nonce(page),
                "nome": "Maria Silva", "whatsapp": "(91) 98273-6418", "quantity": "1",
                "nfc_local_delivery": "yes", "consentimento": "yes", "termos": "yes",
                "nfc_delivery_region": "local", "nfc_cep": "123",
                "nfc_city": "Belém", "nfc_state": "PA",
            })
            self.assertEqual(result.status_code, 422)
            text = result.get_data(as_text=True)
            self.assertIn('value="Maria Silva"', text)
            self.assertIn("Informe um CEP", text)
            self.assertIn("logradouro", text)

    def test_nfc_sale_is_locked_when_stock_not_verified(self):
        from app import CheckoutOrder
        with patch.dict(os.environ, {"GTECH_NFC_INITIAL_STOCK": "",
                                     "GTECH_NFC_SALES_ENABLED": "true"}), patch(
                                     "app._checkout_enabled", return_value=True), patch(
                                     "app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            self.assertIn("Compra online de NFC ainda não liberada", page.get_data(as_text=True))
            with app.app_context():
                self.assertEqual(CheckoutOrder.query.count(), 0)

    def test_nfc_cannot_buy_without_delivery_confirmation(self):
        with patch.dict(os.environ, {"GTECH_NFC_INITIAL_STOCK": "8",
                                     "GTECH_NFC_SALES_ENABLED": "true"}), patch(
                                     "app._checkout_enabled", return_value=True), patch(
                                     "app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/nfc")
            with self.client.session_transaction() as sess:
                token = sess["checkout_csrf"]
            resp = self.client.post("/comprar/nfc", data={
                "csrf_token": token, "checkout_intent": self.checkout_nonce(page), "nome": "Comprador Exemplo",
                "whatsapp": "(91) 98273-6418", "quantity": "2",
                **self.nfc_shipping(), "consentimento": "yes", "termos": "yes"})
            self.assertEqual(resp.status_code, 422)
            self.assertIn("Confirme que a entrega", resp.get_data(as_text=True))

    def test_checkout_disabled_until_real_gateway_configured(self):
        for sku in ("foto", "google"):
            page = self.client.get("/comprar/" + sku)
            self.assertEqual(page.status_code, 200)
            self.assertIn("temporariamente indisponível", page.get_data(as_text=True))
            self.assertNotIn('<form ', page.get_data(as_text=True))
            self.assertEqual(self.client.post("/comprar/" + sku, data={"nome": "Teste"}).status_code, 503)
        self.assertEqual(self.client.get("/comprar/nfc").status_code, 200)
        self.assertIn("Compra online de NFC ainda não liberada", self.client.get("/comprar/nfc").get_data(as_text=True))
        with app.app_context():
            self.assertEqual(Lead.query.count(), 0)

    def test_single_catalog_prices_match_display_and_checkout(self):
        from app import CHECKOUT_OFFERS, CATALOGO_GTECH
        products=CATALOGO_GTECH["produtos"]
        self.assertEqual(len(products), 6)
        self.assertEqual(products["nfc"]["preco_centavos"], 7999)
        self.assertEqual(products["site"]["preco_centavos"], 50000)
        self.assertEqual(products["foto"]["preco_centavos"], 1000)
        self.assertEqual(products["google"]["preco_centavos"], 15000)
        self.assertEqual(products["cardapio"]["preco_centavos"], None)
        self.assertEqual(CATALOGO_GTECH["planos"]["site_manutencao"]["preco_centavos"], 14999)
        self.assertEqual(CATALOGO_GTECH["planos"]["site_sem_setup"]["preco_centavos"], 12999)
        self.assertEqual(set(CHECKOUT_OFFERS), {"foto", "google", "nfc"})
        self.assertEqual(CHECKOUT_OFFERS["nfc"]["max_quantity"], 8)
        for service in SERVICES:
            self.assertEqual(service["price"], products[service["id"]]["preco_exibicao"])

    def test_direct_mercadopago_checkout_uses_server_amount_not_browser_input(self):
        import io
        import json
        from app import CheckoutOrder
        captured=[]
        class FakeHTTP(io.BytesIO):
            status = 201
            def __enter__(self): return self
            def __exit__(self,*_args): return False

        def fake_urlopen(req, timeout):
            if req.full_url == "https://api.mercadopago.com/users/me":
                self.assertEqual(req.get_method(), "GET")
                return FakeHTTP(json.dumps({"id": 12345678}).encode("utf-8"))
            payload=json.loads(req.data.decode("utf-8"))
            self.assertEqual(req.full_url,"https://api.mercadopago.com/checkout/preferences")
            self.assertEqual(req.get_method(),"POST")
            self.assertTrue(req.headers.get("Authorization","").startswith("Bearer APP_USR-test-"))
            self.assertEqual(payload["items"][0]["unit_price"],10)
            self.assertEqual(payload["items"][0]["currency_id"],"BRL")
            self.assertEqual(payload["items"][0]["quantity"],1)
            self.assertEqual(payload["external_reference"],"GTECH-"+req.headers["X-idempotency-key"])
            self.assertEqual(payload["notification_url"],
                "https://gtech-oficial.up.railway.app/webhooks/mercadopago")
            captured.append(payload)
            return FakeHTTP(json.dumps({
                "id":"pref-test-only",
                "init_point":"https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=mock"
            }).encode("utf-8"))

        env={
            "GTECH_CHECKOUT_ENABLED":"true",
            "MERCADOPAGO_ACCESS_TOKEN":"APP_USR-test-credential-not-valid",
            "MERCADOPAGO_WEBHOOK_SECRET":"unit-test-key-gtech-signed-webhook-only",
            "MERCADOPAGO_COLLECTOR_ID":"12345678",
            "MERCADOPAGO_CNPJ_VERIFIED":"true",
            "RAILWAY_ENVIRONMENT":"production",
        }
        with patch.dict(os.environ,env), patch("app._secure_db_available",return_value=True):
            page=self.client.get("/comprar/foto")
            self.assertEqual(page.status_code,200)
            self.assertIn(b"Ir ao Mercado Pago",page.data)
            with self.client.session_transaction() as sess:
                token=sess["checkout_csrf"]
            with patch("urllib.request.urlopen",side_effect=fake_urlopen):
                response=self.client.post("/comprar/foto",data={
                    "csrf_token":token,"checkout_intent":self.checkout_nonce(page),"nome":"Cliente Exemplo",
                    "whatsapp":"(91) 98273-6418","consentimento":"yes", "termos":"yes",
                    "price":"1","total_cents":"1",
                })
        self.assertEqual(response.status_code,303,response.get_data(as_text=True))
        self.assertTrue(response.location.startswith("https://www.mercadopago.com.br/checkout/"))
        self.assertEqual(len(captured),1)
        with app.app_context():
            self.assertEqual(CheckoutOrder.query.count(),1)
            order=CheckoutOrder.query.one()
            self.assertEqual(order.total_cents,1000)
            self.assertEqual(order.status,"pending")
            self.assertEqual(Lead.query.count(),1)

    def test_cnpj_confirmation_required_even_if_checkout_flag_and_secrets_set(self):
        env = {
            "GTECH_CHECKOUT_ENABLED": "true",
            "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-unit-test-only",
            "MERCADOPAGO_WEBHOOK_SECRET": "unit-test-hmac-key-longer-than-16",
            "MERCADOPAGO_COLLECTOR_ID": "12345678",
            "MERCADOPAGO_CNPJ_VERIFIED": "false",
            "RAILWAY_ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env), patch("app._secure_db_available", return_value=True):
            page = self.client.get("/comprar/foto")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn('<form ', page.get_data(as_text=True))
            self.assertEqual(self.client.post("/comprar/foto", data={"nome": "Teste"}).status_code, 503)

    def test_checkout_refuses_wrong_merchant_even_when_credentials_are_present(self):
        from app import _create_mercadopago_preference, CheckoutOrder
        from unittest.mock import MagicMock
        env = {"MERCADOPAGO_COLLECTOR_ID": "12345678"}
        order = CheckoutOrder(id="00000000-0000-4000-8000-000000000000",
                              lead_id=1, sku="foto", quantity=1, total_cents=1000,
                              status="pending")
        with patch.dict(os.environ, env):
            with patch("app._mp_request", return_value={"id": 99999}) as request_mock:
                with self.assertRaises(RuntimeError):
                    _create_mercadopago_preference(order, "Restauração de foto")
                request_mock.assert_called_once_with("/users/me")
            with patch("app._mp_request", side_effect=[
                {"id": 12345678},
                {"id": "test-pref", "collector_id": 99999,
                 "init_point": "https://www.mercadopago.com.br/checkout/v1/redirect?id=mock"}
            ]):
                with self.assertRaises(RuntimeError):
                    _create_mercadopago_preference(order, "Restauração de foto")

    def test_payment_api_verifies_amount_merchant_and_reference(self):
        from app import CheckoutOrder, _reconcile_mercadopago_payment
        import uuid
        order_id=str(uuid.uuid4())
        with app.app_context():
            lead=Lead(nome="Cliente Exemplo",whatsapp="91982736418",negocio="Teste",
                      servico="Fotos ou Restauração",prazo="agora",
                      objetivo="Restaurar fotografia",origem="checkout_gtech")
            db.session.add(lead)
            db.session.flush()
            db.session.add(CheckoutOrder(id=order_id,lead_id=lead.id,sku="foto",
                                         quantity=1,total_cents=1000,status="pending"))
            db.session.commit()
            good={"id":1234567,"live_mode":True,"external_reference":"GTECH-"+order_id,"currency_id":"BRL",
                  "collector_id":12345678,"transaction_amount":10.00,"status":"approved"}
            with patch.dict(os.environ,{"MERCADOPAGO_COLLECTOR_ID":"12345678"}):
                # Production rejects test, unverified environment, wrong ID/currency and fractional cents.
                invalid = [{"live_mode": False}, {"live_mode": None}, {"live_mode": "true"},
                           {"id": 7654321}, {"currency_id": "USD"}, {"transaction_amount": 10.001},
                           {"transaction_amount": "NaN"}]
                for change in invalid:
                    with self.subTest(change=change), patch("app._mp_request", return_value={**good, **change}):
                        self.assertFalse(_reconcile_mercadopago_payment("1234567"))
                from app import CheckoutPaymentDelivery
                self.assertEqual(CheckoutPaymentDelivery.query.count(), 0)
                without_mode = {key: value for key, value in good.items() if key != "live_mode"}
                with patch("app._mp_request", return_value=without_mode):
                    self.assertFalse(_reconcile_mercadopago_payment("1234567"))
                with patch("app._mp_request", return_value={**good, "status": "authorized"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"authorized")
                with patch("app._mp_request", return_value={**good, "status": "pending"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                with patch("app._mp_request",return_value={**good,"transaction_amount":1}):
                    self.assertFalse(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"pending")
                with patch("app._mp_request",return_value={**good,"collector_id":1234}):
                    self.assertFalse(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"pending")
                with patch("app._mp_request",return_value={**good,"external_reference":"GTECH-other"}):
                    self.assertFalse(_reconcile_mercadopago_payment("1234567"))
                with patch("app._mp_request",return_value=good):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"approved")
                with patch("app._mp_request", return_value={**good, "status": "in_mediation"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"in_mediation")
                page = self.client.get("/pedido/" + order_id).get_data(as_text=True)
                self.assertIn("Pagamento em disputa", page)
                self.assertNotIn("Pagamento confirmado pela API", page)
                with patch("app._mp_request", return_value={**good, "status": "charged_back"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                page = self.client.get("/pedido/" + order_id).get_data(as_text=True)
                self.assertIn("Pagamento em contestação", page)
                with patch("app._mp_request",return_value={**good,"status":"refunded"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"refunded")

    def test_payment_outbox_retries_failure_and_signs_exact_body(self):
        import hashlib
        import hmac
        import io
        import json
        import uuid
        from datetime import datetime, timedelta
        from app import (CheckoutOrder, CheckoutPaymentDelivery, _reconcile_mercadopago_payment,
                         retry_pending_payments, sync_payment_to_crm)
        order_id = str(uuid.uuid4())
        secret = "test-shared-payment-key-" + "a" * 32
        with app.app_context():
            lead = Lead(nome="Cliente Exemplo", whatsapp="91982736418", negocio="Teste",
                        servico="Fotos ou Restauração", prazo="agora", objetivo="Restaurar foto")
            db.session.add(lead)
            db.session.flush()
            db.session.add(CheckoutOrder(id=order_id, lead_id=lead.id, sku="foto", total_cents=1000))
            db.session.add(ConsentEvidence(lead_id=lead.id, purpose="checkout", terms_version="2026-11-16"))
            db.session.commit()
            good = {"id": 1234567, "live_mode": True, "external_reference": "GTECH-" + order_id, "currency_id": "BRL",
                    "collector_id": 12345678, "transaction_amount": 10, "status": "approved"}
            with patch.dict(os.environ, {"MERCADOPAGO_COLLECTOR_ID": "12345678",
                                        "CRM_PAYMENT_SYNC_ENABLED": "true", "GTECH_SITE_LEAD_SECRET": secret}):
                with patch("app._mp_request", return_value=good), patch("urllib.request.urlopen", side_effect=TimeoutError):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                queued = db.session.get(CheckoutPaymentDelivery, "1234567")
                self.assertEqual(queued.delivered_revision, 0)
                self.assertEqual(queued.attempts, 1)
                self.assertEqual(db.session.get(CheckoutOrder, order_id).status, "approved")
                queued.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
                db.session.commit()
                def receive(req, **kwargs):
                    self.assertEqual(req.full_url, "https://web-production-846ce.up.railway.app/api/integrations/site-payments")
                    timestamp = req.get_header("X-gtech-timestamp")
                    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + req.data, hashlib.sha256).hexdigest()
                    self.assertEqual(req.get_header("X-gtech-signature"), "sha256=" + digest)
                    body = json.loads(req.data)
                    self.assertEqual(body["paymentId"], "1234567")
                    self.assertEqual(body["amountCents"], 1000)
                    self.assertEqual(body["phone"], "5591982736418")
                    self.assertEqual(body["termsVersion"], "2026-11-16")
                    response = io.BytesIO(b'{"ok":true}')
                    response.status = 200
                    return response
                with patch("urllib.request.urlopen", side_effect=receive) as receiver:
                    self.assertEqual(retry_pending_payments(), 1)
                    self.assertTrue(sync_payment_to_crm("1234567"))
                    self.assertEqual(receiver.call_count, 1)
                db.session.refresh(queued)
                self.assertEqual(queued.revision, queued.delivered_revision)
                # A refund notification schedules another delivery for the same payment.
                with patch("app._mp_request", return_value={**good, "status": "refunded"}), patch("urllib.request.urlopen", side_effect=TimeoutError):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertGreater(queued.revision, queued.delivered_revision)
                self.assertEqual(db.session.get(CheckoutOrder, order_id).status, "refunded")

    def test_rejected_card_retry_does_not_erase_an_approved_payment(self):
        import uuid
        from app import CheckoutOrder, _reconcile_mercadopago_payment, CheckoutPaymentDelivery
        order_id = str(uuid.uuid4())
        with app.app_context():
            lead = Lead(nome="Cliente Exemplo", whatsapp="91982736418", negocio="Teste",
                        servico="Fotos ou Restauração", prazo="agora", objetivo="Restaurar foto")
            db.session.add(lead)
            db.session.flush()
            db.session.add(CheckoutOrder(id=order_id, lead_id=lead.id, sku="foto", total_cents=1000))
            db.session.commit()
            good = {"id": 1234567, "live_mode": True, "external_reference": "GTECH-" + order_id, "currency_id": "BRL",
                    "collector_id": 12345678, "transaction_amount": 10, "status": "approved"}
            with patch.dict(os.environ, {"MERCADOPAGO_COLLECTOR_ID": "12345678"}):
                with patch("app._mp_request", return_value=good):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                with patch("app._mp_request", return_value={**good, "id": 1234568, "status": "rejected"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234568"))
            self.assertEqual(db.session.get(CheckoutOrder, order_id).status, "approved")
            self.assertEqual(CheckoutPaymentDelivery.query.count(), 2)

    def test_mercadopago_webhook_requires_signature_and_authentication(self):
        import time
        import hmac
        import hashlib
        from app import _verified_mercadopago_webhook
        payload={"data":{"id":"123456789"}}
        env={
            "MERCADOPAGO_WEBHOOK_SECRET":"unit-test-secret-shared-for-hmac",
        }
        ts=str(int(time.time()*1000))
        rid="req-mp-123"
        manifest=f"id:123456789;request-id:{rid};ts:{ts};"
        signature=hmac.new(env["MERCADOPAGO_WEBHOOK_SECRET"].encode(),manifest.encode(),hashlib.sha256).hexdigest()
        with patch.dict(os.environ,env),patch("app._checkout_enabled",return_value=True):
            invalid=self.client.post("/webhooks/mercadopago",json=payload)
            self.assertEqual(invalid.status_code,401)
            with patch("app._reconcile_mercadopago_payment",return_value=True) as sync:
                result=self.client.post("/webhooks/mercadopago",json=payload,headers={
                    "X-Signature":f"ts={ts},v1={signature}",
                    "X-Request-Id":rid
                })
                self.assertEqual(result.status_code,200)
                sync.assert_called_once_with("123456789")

    def test_preview_checkout_is_read_only_and_never_charges(self):
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "preview",
                                    "GTECH_CHECKOUT_ENABLED": "true",
                                    "MERCADOPAGO_ACCESS_TOKEN": "APP_USR-test-only",
                                    "MERCADOPAGO_WEBHOOK_SECRET": "unit-secret-not-live-123456",
                                    "MERCADOPAGO_COLLECTOR_ID": "12345678"}):
            page=self.client.get("/comprar/foto")
            self.assertEqual(page.status_code,200)
            self.assertIn(b"Pagamento indispon",page.data)
            home=self.client.get("/")
            self.assertIn(b"Visualizar compra",home.data)
            with patch("urllib.request.urlopen",side_effect=AssertionError("No payment network calls in preview")):
                blocked=self.client.post("/comprar/foto",data={"nome":"Cliente de Teste"})
            self.assertEqual(blocked.status_code,503)
            with app.app_context():
                self.assertEqual(Lead.query.count(),0)

    def test_payment_return_query_cannot_fake_approval(self):
        from app import CheckoutOrder
        import uuid
        order_id=str(uuid.uuid4())
        with app.app_context():
            lead=Lead(nome="Cliente Exemplo",whatsapp="91982736418",negocio="Teste",
                      servico="Fotos ou Restauração",prazo="agora",
                      objetivo="Restauração de fotografia",origem="checkout_gtech")
            db.session.add(lead)
            db.session.flush()
            db.session.add(CheckoutOrder(id=order_id,lead_id=lead.id,sku="foto",
                                         quantity=1,total_cents=1000,status="pending"))
            db.session.commit()
        result=self.client.get("/pedido/"+order_id+"?retorno=sucesso")
        self.assertEqual(result.status_code,200)
        self.assertIn(b"Aguardando",result.data)
        with app.app_context():
            self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"pending")

    def test_terms_and_privacy_are_available_and_checkout_requires_terms(self):
        policy=self.client.get("/privacidade")
        self.assertEqual(policy.status_code,200)
        self.assertIn(b"gtech_cookie_choice_v2",policy.data)
        terms=self.client.get("/termos")
        self.assertEqual(terms.status_code,200)
        self.assertIn(b"Termos de servi",terms.data)
        self.assertIn(b"70.125.976/0001-76",terms.data)
        with patch.dict(os.environ,{"RAILWAY_ENVIRONMENT":"preview"}):
            page=self.client.get("/comprar/foto")
            self.assertEqual(page.status_code,200)
            self.assertIn(b'name="termos"',page.data)

    def test_preview_has_editable_form_but_never_collects_real_data(self):
        with patch.dict(os.environ,{"RAILWAY_ENVIRONMENT":"preview"}):
            page=self.client.get("/")
            self.assertEqual(page.status_code,200)
            html=page.get_data(as_text=True)
            self.assertIn('data-demo="true"',html)
            self.assertIn('class="briefing-fields"',html)
            self.assertNotIn('class="briefing-fields" disabled',html)
            self.assertNotIn('class="preview-banner"',html)
            self.assertIn("Ambiente de homologação",html)
            payload=self.lead_data()
            blocked=self.client.post("/lead",data=payload)
            self.assertEqual(blocked.status_code,403)
            with app.app_context():
                self.assertEqual(Lead.query.count(),0)

    def test_security_headers_and_no_shared_cache(self):
        home=self.client.get("/")
        self.assertEqual(home.headers.get("X-Frame-Options"),"DENY")
        self.assertIn("frame-ancestors 'none'",home.headers.get("Content-Security-Policy",""))
        self.assertEqual(home.headers.get("Cross-Origin-Opener-Policy"),"same-origin")
        self.assertEqual(home.headers.get("Cross-Origin-Resource-Policy"),"same-origin")
        self.assertIn("no-store",home.headers.get("Cache-Control",""))
        self.assertNotIn("noindex", home.headers.get("X-Robots-Tag", ""))
        self.assertNotIn("https://www.mercadopago.com.br", home.headers["Content-Security-Policy"])
        checkout = self.client.get("/comprar/foto")
        self.assertIn("noindex", checkout.headers["X-Robots-Tag"])
        self.assertIn("form-action 'self' https://www.mercadopago.com.br https://www.mercadopago.com;", checkout.headers["Content-Security-Policy"])
        self.assertEqual(self.client.get("/termos").status_code,200)

    def test_payment_signature_accepts_both_timestamp_units_and_rejects_replay(self):
        import hashlib, hmac, time
        from app import _verified_mercadopago_webhook
        secret = "isolated-signature-test-no-production-key"
        now = int(time.time())
        for scale in (1, 1000):
            for offset, expected in ((0, True), (-301, False), (301, False)):
                ts = str((now + offset) * scale)
                manifest = f"id:12345;request-id:isolated-request;ts:{ts};"
                digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
                headers = {"X-Request-Id": "isolated-request", "X-Signature": f"ts={ts},v1={digest}"}
                with patch.dict(os.environ, {"MERCADOPAGO_WEBHOOK_SECRET": secret}), app.test_request_context("/webhooks/mercadopago?data.id=12345", headers=headers):
                    self.assertEqual(_verified_mercadopago_webhook("12345"), expected)
                    self.assertFalse(_verified_mercadopago_webhook("99999"))

    def test_landing_page_tracks_checkout_availability_without_stale_faq(self):
        for enabled in (False, True):
            with patch("app._checkout_enabled", return_value=enabled):
                html = self.client.get("/").get_data(as_text=True)
            self.assertIn('id="comprar"', html)
            self.assertIn('/comprar/foto', html)
            self.assertIn('/comprar/google', html)
            self.assertNotIn("O site já cobra automaticamente?", html)
            self.assertEqual("Pagamento online disponível" in html, enabled)
            self.assertEqual("Continuar para pagamento" in html, enabled)

    def test_admin_bruteforce_is_throttled_without_exposing_leads(self):
        for _ in range(8):
            res=self.client.get("/admin/leads")
            self.assertEqual(res.status_code,401)
        blocked=self.client.get("/admin/leads")
        self.assertEqual(blocked.status_code,429)
        self.assertNotIn(b"Cliente Exemplo",blocked.data)

    def test_export_sanitizes_spreadsheet_formula_injection_and_redirect(self):
        import base64
        from app import csv_safe
        self.assertEqual(csv_safe("=1+1"),"'=1+1")
        self.assertEqual(csv_safe("  @SUM(A1:A2)"),"'  @SUM(A1:A2)")
        self.assertEqual(csv_safe("+Evil"),"'+Evil")
        self.assertEqual(csv_safe("Cliente Bom"),"Cliente Bom")
        key=base64.b64encode(b"ci-admin:ci-password-for-tests-only").decode()
        headers={"Authorization":"Basic "+key}
        with app.app_context():
            sample=Lead(nome="=HYPERLINK(123)",whatsapp="91982736418",
                         negocio="  @IMPORT",servico="Site Profissional",prazo="Em até 7 dias",
                         objetivo="=1+2",origem="site")
            db.session.add(sample)
            db.session.commit()
        response=self.client.get("/admin/export.csv",headers=headers)
        self.assertEqual(response.status_code,200)
        content=response.get_data(as_text=True)
        self.assertIn("'=HYPERLINK(123)",content)
        self.assertIn("'  @IMPORT",content)
        self.assertIn("'=1+2",content)
        page=self.client.get("/admin/leads",headers=headers)
        self.assertEqual(page.status_code,200)
        with self.client.session_transaction() as sess:
            token=sess["admin_csrf"]
        with app.app_context():
            ident=Lead.query.first().id
        status=self.client.post(
            f"/admin/leads/{ident}/status",
            data={"admin_csrf":token,"status":"proposta"},
            headers={**headers,"Referer":"https://phishing.example/steal"}
        )
        self.assertTrue(status.headers.get("Location","").endswith("/admin/leads"))

    def test_consent_evidence_is_created_for_live_budget_only(self):
        payload=self.lead_data()
        response=self.client.post("/lead",data=payload)
        self.assertEqual(response.status_code,302)
        with app.app_context():
            logs=ConsentEvidence.query.all()
            self.assertEqual(len(logs),1)
            self.assertEqual(logs[0].purpose,"budget")
            self.assertEqual(logs[0].privacy_version,"2026-11-16")
            self.assertEqual(logs[0].terms_version, "2026-11-16")

    def test_privacy_thanks_and_sitemap(self):
        self.assertEqual(self.client.get("/privacidade").status_code, 200)
        self.assertEqual(self.client.get("/obrigado?lead_id=100").status_code, 200)
        site_map = self.client.get("/sitemap.xml")
        self.assertEqual(site_map.status_code, 200)
        self.assertIn(b"gtech-oficial.up.railway.app", site_map.data)
        self.assertEqual(self.client.get("/health").json["status"], "ok")


if __name__ == "__main__":
    unittest.main()


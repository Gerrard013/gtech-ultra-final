"""Smoke tests for the official G Tech storefront. No remote payment or CRM calls."""
import base64
import os
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
        self.assertEqual(response.status_code, 302)
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
            self.assertEqual(response.status_code, 302, number)
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

    def test_rejects_missing_csrf(self):
        data = self.lead_data()
        data["csrf_token"] = ""
        response = self.client.post("/lead", data=data)
        self.assertEqual(response.status_code, 400)

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


    def test_crm_sync_is_off_until_explicitly_enabled(self):
        from app import sync_lead_to_crm
        with app.app_context():
            lead = Lead(
                nome="Cliente Teste", whatsapp="91982736418", negocio="Teste G Tech",
                servico="Placa NFC Personalizada", prazo="Em até 7 dias",
                objetivo="Demonstração de NFC para estabelecimento", origem="site_test"
            )
            db.session.add(lead)
            db.session.commit()
            with patch.dict(os.environ, {"CRM_LEAD_SYNC_ENABLED": "false",
                                        "CRM_LEAD_CAPTURE_URL": "https://web-production-846ce.up.railway.app/api/public/lead"}):
                with patch("urllib.request.urlopen", side_effect=AssertionError("CRM must not be contacted")):
                    sync_lead_to_crm(lead, "Belém")
            self.assertEqual(Lead.query.count(), 1)

    def test_crm_payload_compatible_with_current_lead_capture_schema(self):
        import json
        from types import SimpleNamespace
        from app import sync_lead_to_crm
        captured = []
        class FakeResponse:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        def fake_urlopen(req, timeout):
            captured.append((req, timeout))
            return FakeResponse()

        with app.app_context():
            lead = Lead(
                nome="Cliente Teste", whatsapp="91982736418", negocio="Loja de Testes",
                servico="Placa NFC Personalizada", prazo="Em até 7 dias",
                objetivo="Quero usar NFC para disponibilizar perfil de contato",
                origem="site_oficial_v2|instagram"
            )
            db.session.add(lead)
            db.session.commit()
            with patch.dict(os.environ, {"CRM_LEAD_SYNC_ENABLED": "true",
                                        "CRM_LEAD_CAPTURE_URL": "https://web-production-846ce.up.railway.app/api/public/lead"}):
                with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    sync_lead_to_crm(lead, "Belém")
            self.assertEqual(Lead.query.count(), 1)
        self.assertEqual(len(captured), 1)
        req, timeout = captured[0]
        self.assertEqual(req.full_url, "https://web-production-846ce.up.railway.app/api/public/lead")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(timeout, 4)
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["phone"], "5591982736418")
        self.assertEqual(payload["city"], "Belém")
        self.assertEqual(payload["product"], "nfc")
        self.assertEqual(payload["quantity"], 1)
        self.assertEqual(payload["start"], "30_dias")
        self.assertIs(payload["consent"], True)
        self.assertEqual(payload["website"], "")
        self.assertIn("Nenhum pagamento foi confirmado", payload["details"])
        self.assertTrue(len(payload["details"]) <= 900)

    def test_crm_network_failure_keeps_original_lead(self):
        from app import sync_lead_to_crm
        with app.app_context():
            lead = Lead(
                nome="Cliente Teste", whatsapp="91982736418", negocio="Empresa Teste",
                servico="Site Profissional", prazo="Estou pesquisando",
                objetivo="Preciso de uma vitrine digital para agendamentos",
                origem="site_test"
            )
            db.session.add(lead)
            db.session.commit()
            lead_id=lead.id
            with patch.dict(os.environ, {"CRM_LEAD_SYNC_ENABLED": "true",
                                        "CRM_LEAD_CAPTURE_URL": "https://web-production-846ce.up.railway.app/api/public/lead"}):
                with patch("urllib.request.urlopen", side_effect=TimeoutError("No network in tests")):
                    sync_lead_to_crm(lead, "Belém")
            self.assertIsNotNone(db.session.get(Lead, lead_id))

    def test_checkout_disabled_until_real_gateway_configured(self):
        self.assertEqual(self.client.get("/comprar/foto").status_code, 503)
        self.assertEqual(self.client.get("/comprar/google").status_code, 503)
        self.assertEqual(self.client.get("/comprar/nfc").status_code, 404)

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
        self.assertEqual(set(CHECKOUT_OFFERS), {"foto", "google"})
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
            payload=json.loads(req.data.decode("utf-8"))
            self.assertEqual(req.full_url,"https://api.mercadopago.com/checkout/preferences")
            self.assertEqual(req.get_method(),"POST")
            self.assertTrue(req.headers.get("Authorization","").startswith("Bearer APP_USR-test-"))
            self.assertEqual(payload["items"][0]["unit_price"],10)
            self.assertEqual(payload["items"][0]["currency_id"],"BRL")
            self.assertEqual(payload["items"][0]["quantity"],1)
            self.assertEqual(payload["external_reference"],"GTECH-"+req.headers["X-idempotency-key"])
            self.assertEqual(payload["notification_url"],
                "https://gtech-ultra-final-production.up.railway.app/webhooks/mercadopago")
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
                    "csrf_token":token,"nome":"Cliente Exemplo",
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
            good={"external_reference":"GTECH-"+order_id,"currency_id":"BRL",
                  "collector_id":12345678,"transaction_amount":10.00,"status":"approved"}
            with patch.dict(os.environ,{"MERCADOPAGO_COLLECTOR_ID":"12345678"}):
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
                with patch("app._mp_request",return_value={**good,"status":"refunded"}):
                    self.assertTrue(_reconcile_mercadopago_payment("1234567"))
                self.assertEqual(db.session.get(CheckoutOrder,order_id).status,"refunded")

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
        self.assertEqual(self.client.get("/termos").status_code,200)

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
            self.assertIsNone(logs[0].terms_version)

    def test_privacy_thanks_and_sitemap(self):
        self.assertEqual(self.client.get("/privacidade").status_code, 200)
        self.assertEqual(self.client.get("/obrigado?lead_id=100").status_code, 200)
        site_map = self.client.get("/sitemap.xml")
        self.assertEqual(site_map.status_code, 200)
        self.assertIn(b"gtech-ultra-final-production.up.railway.app", site_map.data)
        self.assertEqual(self.client.get("/health").json["status"], "ok")


if __name__ == "__main__":
    unittest.main()

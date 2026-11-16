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

from app import app, db, Lead, SERVICES, _lead_attempts, _lead_attempts_lock, normalize_mobile


class OfficialSiteTests(unittest.TestCase):
    def setUp(self):
        assert "sqlite" in app.config["SQLALCHEMY_DATABASE_URI"]
        app.config["TESTING"] = True
        with _lead_attempts_lock:
            _lead_attempts.clear()
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

    def test_checkout_fixed_price_signed_bridge_without_real_transaction(self):
        import io
        import json
        import hmac
        import hashlib
        from app import CheckoutOrder
        shared="test-only-checkout-secret-with-more-than-32-characters"
        captured=[]
        class FakeHTTP(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self,*_args): return False

        def fake_urlopen(req, timeout):
            body=json.loads(req.data.decode("utf-8"))
            signature=req.headers.get("X-gtech-signature") or req.headers.get("X-GTech-Signature")
            expected="sha256="+hmac.new(shared.encode(),req.data,hashlib.sha256).hexdigest()
            self.assertEqual(signature,expected)
            self.assertEqual(req.full_url,"https://metasimples-production.up.railway.app/api/gtech/checkout")
            self.assertEqual(body["sku"],"foto")
            self.assertEqual(body["quantity"],1)
            captured.append(body)
            response={
                "order_id":body["order_id"],"amount_cents":1000,
                "checkout_url":"https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=unit-test"
            }
            return FakeHTTP(json.dumps(response).encode("utf-8"))

        with patch.dict(os.environ,{"GTECH_CHECKOUT_ENABLED":"true",
                                   "GTECH_CHECKOUT_SHARED_SECRET":shared}):
            page=self.client.get("/comprar/foto")
            self.assertEqual(page.status_code,200)
            self.assertIn(b"Ir ao Mercado Pago",page.data)
            with self.client.session_transaction() as sess:
                token=sess["checkout_csrf"]
            with patch("urllib.request.urlopen",side_effect=fake_urlopen):
                result=self.client.post("/comprar/foto",data={
                    "csrf_token":token,"nome":"Cliente Exemplo",
                    "whatsapp":"(91) 98273-6418",
                    "consentimento":"yes",
                    "price":"1",
                })
            self.assertEqual(result.status_code,303,result.get_data(as_text=True))
            self.assertTrue(result.location.startswith("https://www.mercadopago.com.br/checkout/"))
            with app.app_context():
                self.assertEqual(CheckoutOrder.query.count(),1)
                order=CheckoutOrder.query.one()
                self.assertEqual(order.total_cents,1000)
                self.assertEqual(order.status,"pending")
                self.assertEqual(Lead.query.count(),1)
            self.assertEqual(len(captured),1)

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

    def test_privacy_thanks_and_sitemap(self):
        self.assertEqual(self.client.get("/privacidade").status_code, 200)
        self.assertEqual(self.client.get("/obrigado?lead_id=100").status_code, 200)
        site_map = self.client.get("/sitemap.xml")
        self.assertEqual(site_map.status_code, 200)
        self.assertIn(b"gtech-ultra-final-production.up.railway.app", site_map.data)
        self.assertEqual(self.client.get("/health").json["status"], "ok")


if __name__ == "__main__":
    unittest.main()

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

    def test_privacy_thanks_and_sitemap(self):
        self.assertEqual(self.client.get("/privacidade").status_code, 200)
        self.assertEqual(self.client.get("/obrigado?lead_id=100").status_code, 200)
        site_map = self.client.get("/sitemap.xml")
        self.assertEqual(site_map.status_code, 200)
        self.assertIn(b"gtech-ultra-final-production.up.railway.app", site_map.data)
        self.assertEqual(self.client.get("/health").json["status"], "ok")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import re
import secrets
import threading
import uuid
import time
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections import defaultdict, deque
from functools import wraps
from urllib.parse import quote, urlsplit

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    send_from_directory,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_
from werkzeug.middleware.proxy_fix import ProxyFix


def normalize_database_url(url: str | None) -> str:
    if not url:
        return ""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

app = Flask(__name__, instance_path=INSTANCE_DIR)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    SQLALCHEMY_DATABASE_URI=normalize_database_url(
        os.getenv("DATABASE_URL")
    )
    or "sqlite:///gtech_leads.db",
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=1800,
)

if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("FLASK_ENV") == "production":
    app.config["SESSION_COOKIE_SECURE"] = True


db = SQLAlchemy(app)


class Lead(db.Model):
    __tablename__ = "leads"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    whatsapp = db.Column(db.String(40), nullable=False)
    negocio = db.Column(db.String(180), nullable=False)
    servico = db.Column(db.String(120), nullable=False)
    prazo = db.Column(db.String(120), nullable=False)
    objetivo = db.Column(db.Text, nullable=False)
    mensagem = db.Column(db.Text, nullable=True)
    origem = db.Column(db.String(180), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="novo")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    @property
    def whatsapp_link(self) -> str:
        digits = re.sub(r"\D", "", self.whatsapp or "")
        if len(digits) in (10, 11):
            digits = "55" + digits
        message = (
            f"Olá, {self.nome}! Aqui é da G Tech. "
            f"Recebemos seu diagnóstico sobre {self.servico}."
        )
        return f"https://wa.me/{digits}?text={quote(message)}" if digits else "#"


class ConsentEvidence(db.Model):
    """Minimal evidence of the notice shown and the declared purpose, without raw IPs."""
    __tablename__ = "gtech_consent_evidence"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False)  # "budget" or "checkout"
    privacy_version = db.Column(db.String(15), nullable=False, default="2026-11-16")
    terms_version = db.Column(db.String(15), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class CheckoutOrder(db.Model):
    """One-off storefront checkout; no amount, token, or PII in public redirects."""
    __tablename__ = "gtech_checkout_orders"
    id = db.Column(db.String(36), primary_key=True)
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), nullable=False, index=True)
    sku = db.Column(db.String(40), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    total_cents = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending")
    checkout_url = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# The catalogue is the single source of prices for both storefront and Checkout Pro.
# Prices in cents are edited in config/catalogo_gtech.json, NEVER in checkout URLs.
with open(os.path.join(BASE_DIR, "config", "catalogo_gtech.json"), encoding="utf-8") as catalog_file:
    CATALOGO_GTECH = json.load(catalog_file)

CATALOG_PRODUCTS = CATALOGO_GTECH["produtos"]
CHECKOUT_OFFERS = {}
for _sku, _item in CATALOG_PRODUCTS.items():
    _cents = _item.get("preco_centavos")
    if _item.get("checkout_direto"):
        if not isinstance(_cents, int) or isinstance(_cents, bool) or _cents <= 0:
            raise ValueError("Preço de checkout inválido no catálogo: " + _sku)
        CHECKOUT_OFFERS[_sku] = {
            "title": _item["titulo"],
            "cents": _cents,
            "description": _item.get("observacao", ""),
        }


def _mp_credentials_ready() -> bool:
    """Only a dedicated production G Tech merchant account can receive payments."""
    token = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip()
    signature_key = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
    collector_id = os.getenv("MERCADOPAGO_COLLECTOR_ID", "").strip()
    return (token.startswith("APP_USR-") and len(signature_key) >= 16
            and collector_id.isdigit() and len(collector_id) >= 4)


def _secure_db_available() -> bool:
    """Do not accept money if storage is an ephemeral SQLite volume."""
    return db.engine.url.get_backend_name().startswith("postgresql")


def _checkout_enabled() -> bool:
    return (os.getenv("GTECH_CHECKOUT_ENABLED", "false").lower() == "true"
            and os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() != "preview"
            and _mp_credentials_ready() and _secure_db_available())


def _is_mercadopago_link(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return parts.scheme == "https" and not parts.username and not parts.password and (
            host in {"mercadopago.com.br", "mercadopago.com"} or
            host.endswith(".mercadopago.com.br") or host.endswith(".mercadopago.com")
        )
    except ValueError:
        return False


def _mp_request(path: str, data: dict | None = None, *, timeout: int = 12, request_id: str = "") -> dict:
    """Server-side Mercado Pago API. Never log the access token or return API error bodies."""
    token = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Mercado Pago não configurado")
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8") if data is not None else None
    headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        if request_id:
            headers["X-Idempotency-Key"] = request_id
    req = urllib.request.Request(
        "https://api.mercadopago.com" + path,
        data=payload, headers=headers,
        method="POST" if payload is not None else "GET"
    )
    with urllib.request.urlopen(req, timeout=timeout) as reply:
        if getattr(reply, "status", 200) >= 400:
            raise RuntimeError("Mercado Pago recusou operação")
        data = json.load(reply)
    if not isinstance(data, dict):
        raise ValueError("Resposta inesperada do gateway")
    return data


def _create_mercadopago_preference(order: CheckoutOrder, title: str) -> str:
    """The price is read from the persisted order, not from the request/browser."""
    base = "https://gtech-ultra-final-production.up.railway.app"
    item = {
        "id": order.sku,
        "title": title,
        "currency_id": "BRL",
        "quantity": order.quantity,
        "unit_price": order.total_cents / (100 * order.quantity),
    }
    payload = {
        "items": [item],
        "external_reference": "GTECH-" + order.id,
        "notification_url": base + "/webhooks/mercadopago",
        "back_urls": {
            "success": base + "/pedido/" + order.id + "?retorno=sucesso",
            "pending": base + "/pedido/" + order.id + "?retorno=pendente",
            "failure": base + "/pedido/" + order.id + "?retorno=erro",
        },
        "auto_return": "approved",
        "statement_descriptor": "GTECH",
        "metadata": {"gtech_order_id": order.id, "gtech_sku": order.sku},
    }
    result = _mp_request("/checkout/preferences", payload, request_id=order.id)
    checkout_url = str(result.get("init_point") or "")
    if not _is_mercadopago_link(checkout_url):
        raise ValueError("Checkout inválido devolvido pelo gateway")
    return checkout_url


def _reconcile_mercadopago_payment(payment_id: str, *, order_id: str = "") -> bool:
    """Only Mercado Pago's authenticated API can set order.status = approved."""
    if not re.fullmatch(r"[0-9]{1,25}", str(payment_id)):
        return False
    data = _mp_request("/v1/payments/" + str(payment_id))
    external_reference = str(data.get("external_reference") or "")
    if not external_reference.startswith("GTECH-"):
        return False
    pid = external_reference.removeprefix("GTECH-")
    if order_id and pid != order_id:
        return False
    order = db.session.get(CheckoutOrder, pid)
    if not order:
        return False
    if data.get("currency_id") != "BRL" or str(data.get("collector_id")) != os.getenv("MERCADOPAGO_COLLECTOR_ID", "").strip():
        app.logger.warning("Mercado Pago: recebedor/moeda divergem do pedido %s", pid)
        return False
    try:
        received_cents = int((Decimal(str(data.get("transaction_amount"))) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return False
    if received_cents != order.total_cents:
        app.logger.warning("Mercado Pago: valor divergente no pedido %s", pid)
        return False
    status = str(data.get("status") or "")
    allowed = {"approved", "pending", "in_process", "rejected", "cancelled", "refunded", "charged_back"}
    if status not in allowed:
        return False
    if status in {"refunded", "charged_back"}:
        # A later reversal may invalidate a previously approved payment.
        order.status = status
    elif order.status not in {"approved", "refunded", "charged_back"}:
        order.status = status
    db.session.commit()
    return True


def _verified_mercadopago_webhook(payment_id: str) -> bool:
    """Validate x-signature manifest before requesting payment details from API."""
    secret = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "").strip()
    if not secret:
        return False
    signature = request.headers.get("X-Signature", "")
    request_id = request.headers.get("X-Request-Id", "")
    if not request_id or not signature:
        return False
    fields = {}
    for entry in signature.split(","):
        if "=" in entry:
            k, v = entry.split("=", 1)
            fields[k.strip()] = v.strip()
    ts, v1 = fields.get("ts", ""), fields.get("v1", "")
    if not ts.isdigit() or not re.fullmatch(r"[0-9a-fA-F]{64}", v1):
        return False
    if abs(time.time() - int(ts) / 1000) > 300:
        return False
    manifest = f"id:{payment_id.lower()};request-id:{request_id};ts:{ts};"
    expected = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.lower(), v1.lower())


with app.app_context():
    db.create_all()


CONTACTS = {
    "phone": "5591986152222",
    "display_phone": "(91) 98615-2222",
    "instagram": "https://www.instagram.com/gtech_brasil/",
    "threads": "https://www.threads.net/@gtech_brasil",
    "email": "mailto:gtechinnovationsolutions@gmail.com",
    "email_text": "gtechinnovationsolutions@gmail.com",
    "whatsapp": (
        "https://wa.me/5591986152222?text="
        "Ol%C3%A1%21%20Vim%20pelo%20site%20da%20G%20Tech%20e%20quero%20um%20diagn%C3%B3stico."
    ),
}

SERVICES = [
    {
        "id": "nfc", "title": "Placa NFC Personalizada",
        "form_value": "Placa NFC Personalizada", "symbol": "⌁",
        "category": "PRODUTO FÍSICO + DIGITAL", "price": "R$ 79,99",
        "description": "Um toque para abrir perfis, contatos e experiências digitais. Inclui configuração; a entrega segue condições combinadas."
    },
    {
        "id": "site", "title": "Sites Profissionais",
        "form_value": "Site Profissional", "symbol": "◉",
        "category": "PRESENÇA DIGITAL", "price": "A partir de R$ 500",
        "description": "Sua empresa com uma vitrine clara, responsiva e pronta para receber contatos. Manutenção contratada separadamente."
    },
    {
        "id": "google", "title": "Perfil da Empresa no Google", "checkout_sku": "google",
        "form_value": "Perfil da Empresa no Google", "symbol": "⌖",
        "category": "PRESENÇA LOCAL", "price": "R$ 150",
        "description": "Revisão e organização de informações do perfil empresarial, quando elegível. Serviço independente do Google."
    },
    {
        "id": "cardapio", "title": "Cardápios Digitais Premium",
        "form_value": "Cardápio Digital Premium", "symbol": "▦",
        "category": "RESTAURANTES E DELIVERY", "price": "Sob orçamento",
        "description": "Cardápio interativo pensado para celular, com produtos, categorias, QR Code e caminho simples para pedidos."
    },
    {
        "id": "foto", "title": "Restauração de Fotografias", "checkout_sku": "foto",
        "form_value": "Fotos ou Restauração", "symbol": "▧",
        "category": "IMAGEM E MEMÓRIA", "price": "A partir de R$ 10",
        "description": "Recuperação cuidadosa de fotos antigas, preservando características e respeitando a imagem original."
    },
    {
        "id": "automacao", "title": "Automações & Soluções",
        "form_value": "Automação ou Sistema", "symbol": "◇",
        "category": "TECNOLOGIA PARA EMPRESAS", "price": "Sob análise",
        "description": "Organização de processos e projetos digitais sob medida, sujeitos a análise de escopo e enquadramento do serviço."
    },
]

# Keep public price labels synchronized with the same catalogue used by payment logic.
for _service in SERVICES:
    _catalog_item = CATALOG_PRODUCTS.get(_service["id"])
    if _catalog_item:
        _service["price"] = _catalog_item["preco_exibicao"]
        if _catalog_item.get("checkout_direto"):
            _service["checkout_sku"] = _service["id"]
        else:
            _service.pop("checkout_sku", None)


FEEDBACKS = [
    {
        "quote": "Tudo ok, Gerrard. Obrigada. Outro dia mandarei outras fotos.",
        "context": "Cliente de restauração de fotos",
        "image": "feedback-nilse.webp",
    },
    {
        "quote": (
            "Nossa, muito obrigada. Ficou bom demais. Pode deixar que vou te chamar "
            "novamente e te indicar também."
        ),
        "context": "Cliente de edição e restauração",
        "image": "feedback-sara.webp",
    },
]

STATUS_LABELS = {
    "novo": "Novo",
    "contatado": "Contatado",
    "proposta": "Proposta enviada",
    "fechado": "Fechado",
    "arquivado": "Arquivado",
}


@app.after_request
def set_security_headers(response: Response) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains" if request.is_secure else "")
    if not request.is_secure:
        response.headers.pop("Strict-Transport-Security", None)
    response.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-src 'none'"
    ))
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if request.path == "/" or request.path.startswith(("/admin", "/pedido/", "/comprar/")) or request.path == "/obrigado":
        response.headers["Cache-Control"] = "no-store, private"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    if os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview":
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def check_auth(username: str, password: str) -> bool:
    expected_user = os.getenv("ADMIN_USER") or ""
    expected_pass = os.getenv("ADMIN_PASS") or ""
    if not (expected_user and expected_pass):
        return False
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_pass
    )


# Lightweight per-worker admin throttling. For distributed production, add a
# shared WAF/Redis limiter and a separate VPN/zero-trust gate.
_admin_failed: dict[str, deque[float]] = defaultdict(deque)
_admin_failed_lock = threading.Lock()


def _admin_locked(ip: str) -> bool:
    now = time.monotonic()
    with _admin_failed_lock:
        if len(_admin_failed) > 1500:
            for key in list(_admin_failed)[:500]:
                if not _admin_failed[key] or now - _admin_failed[key][-1] > 900:
                    _admin_failed.pop(key, None)
        attempts = _admin_failed[ip]
        while attempts and now - attempts[0] > 900:
            attempts.popleft()
        return len(attempts) >= 8


def _admin_fail(ip: str) -> None:
    with _admin_failed_lock:
        _admin_failed[ip].append(time.monotonic())


def _admin_succeeded(ip: str) -> None:
    with _admin_failed_lock:
        _admin_failed.pop(ip, None)


def requires_auth(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"
        if _admin_locked(ip):
            return Response("Muitas tentativas de acesso. Tente mais tarde.", 429)
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            _admin_fail(ip)
            return Response(
                "Acesso restrito.",
                401,
                {"WWW-Authenticate": 'Basic realm="G Tech Admin"'},
            )
        _admin_succeeded(ip)
        return view_func(*args, **kwargs)

    return decorated


def clean_text(value: str | None, max_length: int) -> str:
    return (value or "").strip()[:max_length]


# Brazilian geographic area codes, following actual NANP-like national numbering groups.
BR_DDDS = {11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,
           41,42,43,44,45,46,47,48,49,51,53,54,55,61,62,63,64,65,66,67,68,69,
           71,73,74,75,77,79,81,82,83,84,85,86,87,88,89,91,92,93,94,95,96,97,98,99}


def normalize_mobile(value: str) -> str | None:
    """Brazilian mobile syntax, not proof that a WhatsApp account exists."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("55") and len(digits) == 13:
        digits = digits[2:]
    if len(digits) != 11 or int(digits[:2]) not in BR_DDDS or digits[2] != "9":
        return None
    subscriber = digits[2:]
    # Obvious dummy/test patterns; don't pretend to verify number ownership.
    if len(set(subscriber)) < 3:
        return None
    tail = subscriber[1:]
    if tail in ("12345678", "87654321", "00000000", "11111111", "22222222",
                "33333333", "44444444", "55555555", "66666666", "77777777",
                "88888888", "99999999"):
        return None
    return digits


def valid_phone(value: str) -> bool:
    return normalize_mobile(value) is not None


# Lightweight single-process protection. Needs a shared Redis/WAF limit before
# production-scale traffic across multiple replicas.
_lead_attempts: dict[str, deque[float]] = defaultdict(deque)
_lead_attempts_lock = threading.Lock()


def excessive_lead_submissions(ip: str) -> bool:
    now = time.monotonic()
    with _lead_attempts_lock:
        if len(_lead_attempts) > 2000:
            # Bound memory in long-running single-process instances.
            for key in list(_lead_attempts)[:500]:
                if not _lead_attempts[key] or now - _lead_attempts[key][-1] > 600:
                    _lead_attempts.pop(key, None)
        events = _lead_attempts[ip]
        while events and now - events[0] > 600:
            events.popleft()
        if len(events) >= 5:
            return True
        events.append(now)
        return False


@app.route("/")
def index():
    if "lead_csrf" not in session:
        session["lead_csrf"] = secrets.token_urlsafe(32)
    return render_template(
        "index.html",
        contacts=CONTACTS,
        services=SERVICES,
        checkout_enabled=_checkout_enabled() or os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview",
        feedbacks=FEEDBACKS,
        year=datetime.utcnow().year,
        csrf_token=session["lead_csrf"],
        belem_video_available=os.path.isfile(os.path.join(BASE_DIR, "static", "media", "belem-studio-nfc.mp4")),
        nfc_video_available=os.path.isfile(
            os.path.join(BASE_DIR, "static", "media", "hero-nfc.mp4")
        ),
        cardapio_video_available=os.path.isfile(
            os.path.join(BASE_DIR, "static", "media", "cardapio-demo.mp4")
        ),
        nfc_demo_video_available=os.path.isfile(
            os.path.join(BASE_DIR, "static", "media", "nfc-demo.mp4")
        ),
        drive_preview_enabled=os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview",
    )


def sync_lead_to_crm(lead: Lead, city: str) -> None:
    """Optional best-effort hand-off; local database is the source of recovery."""
    if os.getenv("CRM_LEAD_SYNC_ENABLED", "false").lower() != "true":
        return
    endpoint = os.getenv("CRM_LEAD_CAPTURE_URL", "").strip()
    # Never send customer data to an unverified or unexpected destination.
    expected = "https://web-production-846ce.up.railway.app/api/public/lead"
    if endpoint != expected:
        logging.warning("G Tech lead sync skipped: CRM endpoint not approved")
        return
    mapping = {
        "Placa NFC Personalizada": "nfc",
        "Site Profissional": "site",
        "Perfil da Empresa no Google": "google",
        "Cardápio Digital Premium": "cardapio",
        "Fotos ou Restauração": "foto",
        "Automação ou Sistema": "automacao",
    }
    product = mapping.get(lead.servico)
    if not product:
        logging.info("G Tech lead kept locally: service not mapped to CRM")
        return
    number = re.sub(r"\D", "", lead.whatsapp)
    if not number.startswith("55"):
        number = "55" + number
    body = {
        "name": lead.nome,
        "company": lead.negocio,
        "phone": number,
        "city": city or "Não informado",
        "sector": "Site oficial G Tech",
        "product": product,
        "quantity": 1,
        "start": (
            "agora" if lead.prazo == "O mais rápido possível"
            else "30_dias" if lead.prazo in ("Em até 7 dias", "Em até 30 dias")
            else "pesquisando"
        ),
        "details": (
            "Origem: site oficial. "
            "Serviço original: " + lead.servico + ". "
            "Necessidade: " + lead.objetivo[:550] + ". "
            "ID interno: " + str(lead.id) + ". "
            "Nenhum pagamento foi confirmado."
        )[:900],
        "consent": True,
        "website": "",
    }
    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            logging.info("G Tech CRM lead sync: HTTP %s", response.status)
    except Exception:
        logging.warning("G Tech CRM lead sync failed; original lead saved locally")


@app.post("/lead")
def create_lead():
    if os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview":
        # Preview has disposable storage; do not accept live personal information.
        abort(403)
    token = request.form.get("csrf_token", "")
    expected_token = session.get("lead_csrf", "")
    if not token or not expected_token or not secrets.compare_digest(token, expected_token):
        abort(400)
    if request.form.get("website"):
        abort(400)
    if excessive_lead_submissions(request.remote_addr or "unknown"):
        return Response("Muitas tentativas. Aguarde alguns minutos antes de enviar novamente.", status=429)
    if request.form.get("consentimento") != "yes":
        flash("É necessário confirmar a Política de Privacidade para enviar o orçamento.", "error")
        return redirect(url_for("index") + "#contato")
    if request.form.get("termos") != "yes":
        flash("Leia e aceite os Termos de Uso da G Tech antes de enviar o orçamento.", "error")
        return redirect(url_for("index") + "#contato")

    nome = clean_text(request.form.get("nome"), 120)
    whatsapp = clean_text(request.form.get("whatsapp"), 40)
    negocio = clean_text(request.form.get("negocio"), 180) or "Cliente interessado"
    servico = clean_text(request.form.get("servico"), 120)
    prazo = clean_text(request.form.get("prazo"), 120) or "Estou pesquisando"
    objetivo = clean_text(request.form.get("objetivo"), 2000)
    mensagem = clean_text(request.form.get("mensagem"), 2000)
    origem = clean_text(request.form.get("origem"), 180)
    cidade = clean_text(request.form.get("cidade"), 100)

    required = [nome, whatsapp, servico, objetivo]
    if len(nome) < 2 or len(objetivo) < 10:
        flash("Informe seu nome e descreva brevemente sua necessidade.", "error")
        return redirect(url_for("index") + "#contato")
    allowed_services = {item["form_value"] for item in SERVICES} | {"Outro serviço"}
    allowed_deadlines = {
        "O mais rápido possível", "Em até 7 dias", "Em até 30 dias", "Estou pesquisando"
    }
    if not all(required) or servico not in allowed_services or prazo not in allowed_deadlines:
        flash("Revise os campos obrigatórios antes de enviar.", "error")
        return redirect(url_for("index") + "#contato")

    if not valid_phone(whatsapp):
        flash("Informe um celular brasileiro válido com DDD e nono dígito. Não aceitamos números de exemplo.", "error")
        return redirect(url_for("index") + "#contato")

    lead = Lead(
        nome=nome,
        whatsapp=normalize_mobile(whatsapp) or whatsapp,
        negocio=negocio,
        servico=servico,
        prazo=prazo,
        objetivo=objetivo,
        mensagem=(("Cidade: " + cidade + "\n") if cidade else "") + mensagem,
        origem=origem,
    )
    db.session.add(lead)
    db.session.flush()
    db.session.add(ConsentEvidence(lead_id=lead.id, purpose="budget", privacy_version="2026-11-16", terms_version="2026-11-16"))
    db.session.commit()
    # Do not fail the customer journey when the CRM integration is unavailable.
    sync_lead_to_crm(lead, cidade)
    return redirect(url_for("thanks"))



@app.route("/comprar/<sku>", methods=["GET", "POST"])
def checkout_product(sku: str):
    if sku not in CHECKOUT_OFFERS:
        abort(404)
    preview_only = os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview"
    if not _checkout_enabled() and not (preview_only and request.method == "GET"):
        abort(503)
    offer = CHECKOUT_OFFERS[sku]
    if "checkout_csrf" not in session:
        session["checkout_csrf"] = secrets.token_urlsafe(32)
    if request.method == "GET":
        return render_template("comprar.html", sku=sku, offer=offer, contacts=CONTACTS,
                               csrf_token=session["checkout_csrf"], preview_only=preview_only)

    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("checkout_csrf", "")):
        abort(400)
    if (request.form.get("website", "") or request.form.get("consentimento") != "yes"
        or request.form.get("termos") != "yes"):
        abort(400)
    if excessive_lead_submissions(request.remote_addr or "unknown"):
        return Response("Muitas tentativas. Tente novamente mais tarde.", status=429)

    name = clean_text(request.form.get("nome"), 100)
    phone = clean_text(request.form.get("whatsapp"), 40)
    if len(name) < 2 or not valid_phone(phone):
        flash("Confira seu nome e celular com DDD.", "error")
        return redirect(url_for("checkout_product", sku=sku))

    lead = Lead(
        nome=name, whatsapp=normalize_mobile(phone) or phone, negocio="Cliente de checkout",
        servico="Fotos ou Restauração" if sku == "foto" else "Perfil da Empresa no Google",
        prazo="O mais rápido possível", objetivo="Pedido G Tech: " + offer["title"],
        origem="checkout_gtech"
    )
    order = CheckoutOrder(
        id=str(uuid.uuid4()), lead_id=0, sku=sku, quantity=1,
        total_cents=offer["cents"], status="pending"
    )
    try:
        db.session.add(lead)
        db.session.flush()
        order.lead_id = lead.id
        db.session.add(order)
        db.session.add(ConsentEvidence(lead_id=lead.id, purpose="checkout", privacy_version="2026-11-16", terms_version="2026-11-16"))
        db.session.commit()
        gateway_url = _create_mercadopago_preference(order, offer["title"])
        order.checkout_url = gateway_url
        db.session.commit()
        session["last_checkout_order"] = order.id
        return redirect(gateway_url, code=303)
    except Exception as exc:
        db.session.rollback()
        app.logger.warning("Mercado Pago: criação indisponível: %s", type(exc).__name__)
        # Preserve lead/order for recovery. Do not declare a payment successful.
        return redirect(url_for("payment_result", order_id=order.id))


@app.post("/webhooks/mercadopago")
def gtech_mercadopago_webhook():
    if not _checkout_enabled():
        return {"status": "unavailable"}, 503
    data = request.get_json(silent=True) or {}
    nested = data.get("data") if isinstance(data, dict) else None
    payment_id = str(
        request.args.get("data.id") or (nested.get("id") if isinstance(nested, dict) else "") or ""
    )
    if not re.fullmatch(r"[0-9]{1,25}", payment_id):
        return {"status": "ignored"}, 200
    if not _verified_mercadopago_webhook(payment_id):
        return {"error": "Assinatura inválida"}, 401
    try:
        if _reconcile_mercadopago_payment(payment_id):
            return {"status": "received"}, 200
    except Exception as exc:
        app.logger.warning("Mercado Pago: webhook sem conciliação: %s", type(exc).__name__)
    return {"status": "pending_verification"}, 202


@app.route("/pedido/<order_id>")
def payment_result(order_id: str):
    try:
        if str(uuid.UUID(order_id, version=4)) != order_id:
            abort(404)
    except ValueError:
        abort(404)
    order = db.session.get(CheckoutOrder, order_id)
    if not order:
        abort(404)
    # A return URL status is never considered proof. The payment ID is also
    # rechecked using the token-bound merchant's API, amount and reference.
    payment_id = str(request.args.get("payment_id") or request.args.get("collection_id") or "")
    if _checkout_enabled() and re.fullmatch(r"[0-9]{1,25}", payment_id):
        try:
            _reconcile_mercadopago_payment(payment_id, order_id=order_id)
        except Exception as exc:
            app.logger.info("Mercado Pago: pagamento em verificação: %s", type(exc).__name__)
    return render_template("pedido.html", order=order, contacts=CONTACTS)


@app.route("/obrigado")
def thanks():
    # Do not expose names or other lead details through guessable URL IDs.
    return render_template(
        "thanks.html",
        contacts=CONTACTS,
        lead=None,
        year=datetime.utcnow().year,
    )


@app.route("/privacidade")
def privacy_policy():
    return render_template("privacidade.html", contacts=CONTACTS, year=datetime.utcnow().year)


@app.route("/termos")
def terms_of_service():
    return render_template("termos.html", contacts=CONTACTS, year=datetime.utcnow().year)


@app.route("/admin/leads")
@requires_auth
def admin_leads():
    if "admin_csrf" not in session:
        session["admin_csrf"] = secrets.token_urlsafe(32)
    query_text = clean_text(request.args.get("q"), 120)
    selected_status = clean_text(request.args.get("status"), 40)

    query = Lead.query
    if query_text:
        pattern = f"%{query_text}%"
        query = query.filter(
            or_(
                Lead.nome.ilike(pattern),
                Lead.whatsapp.ilike(pattern),
                Lead.negocio.ilike(pattern),
                Lead.servico.ilike(pattern),
            )
        )
    if selected_status in STATUS_LABELS:
        query = query.filter(Lead.status == selected_status)

    leads = query.order_by(Lead.created_at.desc()).all()
    counts = {
        "total": Lead.query.count(),
        "novo": Lead.query.filter_by(status="novo").count(),
        "proposta": Lead.query.filter_by(status="proposta").count(),
        "fechado": Lead.query.filter_by(status="fechado").count(),
    }

    return render_template(
        "admin.html",
        leads=leads,
        counts=counts,
        status_labels=STATUS_LABELS,
        selected_status=selected_status,
        query_text=query_text,
        year=datetime.utcnow().year,
        admin_csrf=session["admin_csrf"],
    )


@app.post("/admin/leads/<int:lead_id>/status")
@requires_auth
def update_lead_status(lead_id: int):
    token = request.form.get("admin_csrf", "")
    expected = session.get("admin_csrf", "")
    if not token or not expected or not secrets.compare_digest(token, expected):
        abort(400)
    lead = db.get_or_404(Lead, lead_id)
    new_status = clean_text(request.form.get("status"), 40)
    if new_status not in STATUS_LABELS:
        abort(400)
    lead.status = new_status
    db.session.commit()
    flash("Status atualizado.", "success")
    return redirect(url_for("admin_leads"))


def csv_safe(value: object) -> str:
    """Avoid spreadsheet formula injection when exporting untrusted lead fields."""
    cell = str(value if value is not None else "")
    first = cell.lstrip(" \t\r\n\ufeff")
    if first.startswith(("=", "+", "-", "@")):
        return "'" + cell
    return cell


@app.route("/admin/export.csv")
@requires_auth
def export_csv():
    leads = Lead.query.order_by(Lead.created_at.desc()).all()
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(
        [
            "ID",
            "Data",
            "Nome",
            "WhatsApp",
            "Negócio",
            "Serviço",
            "Prazo",
            "Objetivo",
            "Mensagem",
            "Origem",
            "Status",
        ]
    )
    for lead in leads:
        writer.writerow(
            [
                lead.id,
                lead.created_at.strftime("%d/%m/%Y %H:%M"),
                csv_safe(lead.nome),
                csv_safe(lead.whatsapp),
                csv_safe(lead.negocio),
                csv_safe(lead.servico),
                csv_safe(lead.prazo),
                csv_safe(lead.objetivo),
                csv_safe(lead.mensagem),
                csv_safe(lead.origem),
                csv_safe(STATUS_LABELS.get(lead.status, lead.status)),
            ]
        )

    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=gtech_leads.csv"},
    )


@app.route("/robots.txt")
def robots():
    return send_from_directory(app.static_folder, "robots.txt")


@app.route("/sitemap.xml")
def sitemap():
    base = "https://gtech-ultra-final-production.up.railway.app"
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/</loc></url>"
        f"<url><loc>{base}/privacidade</loc></url>"
        f"<url><loc>{base}/termos</loc></url>"
        "</urlset>"
    )
    return Response(content, mimetype="application/xml")


@app.route("/health")
def health():
    return {"status": "ok", "service": "gtech-site-oficial"}, 200


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html", contacts=CONTACTS), 404


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

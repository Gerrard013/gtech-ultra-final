from __future__ import annotations

import csv
import fcntl
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
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
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
from sqlalchemy.exc import IntegrityError
from werkzeug.middleware.proxy_fix import ProxyFix


def normalize_database_url(url: str | None) -> str:
    if not url:
        return ""
    if url.startswith("postgresql+psycopg://"):
        # Railway PostgreSQL URL may request psycopg3, while this image installs psycopg2-binary.
        return url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# Public site origin for canonical links and payment callbacks (not Host-header-derived).
PUBLIC_SITE_URL = os.getenv("GTECH_PUBLIC_URL", "https://gtech-oficial.up.railway.app").strip().rstrip("/")
_site_parts = urlsplit(PUBLIC_SITE_URL)
if (_site_parts.scheme != "https" or not _site_parts.netloc
        or _site_parts.username or _site_parts.password
        or _site_parts.path or _site_parts.query or _site_parts.fragment):
    raise RuntimeError("GTECH_PUBLIC_URL precisa conter apenas uma origem HTTPS válida.")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

# Production must never silently generate a new signing key at each restart.
_deployed = bool(os.getenv("RAILWAY_ENVIRONMENT")) or os.getenv("FLASK_ENV") == "production"
_signing_key = os.getenv("SECRET_KEY", "")
if _deployed and len(_signing_key) < 32:
    raise RuntimeError("Configure SECRET_KEY com pelo menos 32 caracteres na produção.")
app = Flask(__name__, instance_path=INSTANCE_DIR)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.config.update(
    SECRET_KEY=_signing_key or secrets.token_hex(32),
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


class CrmDelivery(db.Model):
    """Durable site-to-CRM handoff audit. It never stores payment credentials."""
    __tablename__ = "gtech_crm_deliveries"
    lead_id = db.Column(db.Integer, db.ForeignKey("leads.id"), primary_key=True)
    city = db.Column(db.String(100), nullable=False, default="Não informado")
    status = db.Column(db.String(20), nullable=False, default="pending")
    attempts = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)


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


class CheckoutAttempt(db.Model):
    """A signed checkout form nonce can create at most one order."""
    __tablename__ = "gtech_checkout_attempts"
    token_hash = db.Column(db.String(64), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("gtech_checkout_orders.id"), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class NfcInventory(db.Model):
    """Physical NFC stock; decremented under a DB row lock before checkout."""
    __tablename__ = "gtech_nfc_inventory"
    id = db.Column(db.Integer, primary_key=True)
    available = db.Column(db.Integer, nullable=False, default=0)
    __table_args__ = (db.CheckConstraint("available >= 0", name="ck_nfc_stock_nonnegative"),)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class NfcStockMovement(db.Model):
    """Audited manual inventory adjustments; source of truth is the site's database."""
    __tablename__ = "gtech_nfc_stock_movements"
    id = db.Column(db.String(36), primary_key=True)
    delta = db.Column(db.Integer, nullable=False)
    available_before = db.Column(db.Integer, nullable=False)
    available_after = db.Column(db.Integer, nullable=False)
    actor = db.Column(db.String(100), nullable=False)
    reason = db.Column(db.String(240), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class NfcDeliveryAddress(db.Model):
    """Private fulfillment data; never placed in Mercado Pago URLs or public order pages."""
    __tablename__ = "gtech_nfc_delivery_addresses"
    order_id = db.Column(db.String(36), db.ForeignKey("gtech_checkout_orders.id"), primary_key=True)
    cep = db.Column(db.String(8), nullable=False)
    state = db.Column(db.String(2), nullable=False)
    city = db.Column(db.String(90), nullable=False)
    neighborhood = db.Column(db.String(90), nullable=False)
    street = db.Column(db.String(160), nullable=False)
    number = db.Column(db.String(20), nullable=False)
    complement = db.Column(db.String(160), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class NfcStockUnavailable(Exception):
    """There is no confirmed inventory to reserve for this purchase."""


class CheckoutPaymentDelivery(db.Model):
    """Persistent payment outbox: a CRM outage never loses a gateway notification."""
    __tablename__ = "gtech_checkout_payment_deliveries"
    payment_id = db.Column(db.String(25), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("gtech_checkout_orders.id"), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False)
    revision = db.Column(db.Integer, nullable=False, default=1)
    delivered_revision = db.Column(db.Integer, nullable=False, default=0)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    next_attempt_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    delivered_at = db.Column(db.DateTime, nullable=True)


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
            "max_quantity": _item.get("quantidade_maxima_pedido", 1),
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
            and os.getenv("MERCADOPAGO_CNPJ_VERIFIED", "false").lower() == "true"
            and os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() != "preview"
            and _mp_credentials_ready() and _secure_db_available())


def _nfc_initial_units() -> int:
    """Explicit count confirmed by the owner; only seeds the inventory once."""
    raw = os.getenv("GTECH_NFC_INITIAL_STOCK", "").strip()
    if not re.fullmatch(r"[0-9]{1,3}", raw):
        return 0
    units = int(raw)
    return units if 1 <= units <= 500 else 0


def _nfc_available_units() -> int:
    stock = db.session.get(NfcInventory, 1)
    return max(0, stock.available) if stock is not None else _nfc_initial_units()


def _nfc_checkout_enabled() -> bool:
    return (
        _checkout_enabled()
        and os.getenv("GTECH_NFC_SALES_ENABLED", "false").lower() == "true"
        and _nfc_available_units() > 0
        and _secure_db_available()
    )


def _parse_checkout_quantity(sku: str, raw: str | None) -> int | None:
    text = "1" if raw is None else str(raw).strip()
    if not re.fullmatch(r"[1-9][0-9]{0,2}", text):
        return None
    count = int(text)
    max_quantity = CHECKOUT_OFFERS[sku]["max_quantity"]
    if not isinstance(max_quantity, int) or isinstance(max_quantity, bool):
        return None
    return count if 1 <= count <= max_quantity else None


def _new_checkout_intent(sku: str) -> str:
    if "checkout_identity" not in session:
        session["checkout_identity"] = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    identity = session["checkout_identity"]
    manifest = f"{identity}:{sku}:{nonce}"
    signature = hmac.new(str(app.secret_key).encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return nonce + "." + signature


def _valid_checkout_intent(sku: str, value: str) -> bool:
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,64}\.[a-f0-9]{64}", value or ""):
        return False
    identity = session.get("checkout_identity", "")
    if not identity:
        return False
    nonce, signature = value.rsplit(".", 1)
    manifest = f"{identity}:{sku}:{nonce}"
    expected = hmac.new(str(app.secret_key).encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _previous_checkout_attempt(intent_hash: str):
    attempt = db.session.get(CheckoutAttempt, intent_hash)
    if attempt is None:
        return None
    order = db.session.get(CheckoutOrder, attempt.order_id)
    if order is None:
        return Response("Pedido em conferência. Entre em contato com a G Tech.", 409)
    if order.checkout_url and _is_mercadopago_link(order.checkout_url):
        return redirect(order.checkout_url, code=303)
    return redirect(url_for("payment_result", order_id=order.id), code=303)


def _checkout_form_error(sku, offer, preview_only, enabled, values, errors, csrf_token):
    return render_template(
        "comprar.html", sku=sku, offer=offer, contacts=CONTACTS,
        csrf_token=csrf_token, preview_only=preview_only,
        checkout_enabled=enabled, form_values=values,
        form_errors=errors, nfc_available=_nfc_available_units() if sku == "nfc" else 0,
        checkout_intent=values.get("checkout_intent", ""),
    ), 422, {"Cache-Control": "no-store, private"}


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
    """Verify MP account owner, then create preference from a persisted order only."""
    merchant = _mp_request("/users/me")
    expected_collector = os.getenv("MERCADOPAGO_COLLECTOR_ID", "").strip()
    if not expected_collector or str(merchant.get("id") or "") != expected_collector:
        raise RuntimeError("A conta recebedora do Mercado Pago não corresponde ao CNPJ configurado")
    # Defence in depth: never trust amounts or quantities copied from forms/DB.
    if order.sku not in CHECKOUT_OFFERS:
        raise ValueError("Produto não autorizado")
    offer = CHECKOUT_OFFERS[order.sku]
    if (_parse_checkout_quantity(order.sku, str(order.quantity)) != order.quantity
            or order.total_cents != order.quantity * offer["cents"]):
        raise ValueError("Quantidade ou valor de pedido divergente")
    base = PUBLIC_SITE_URL
    item = {
        "id": order.sku,
        "title": title,
        "currency_id": "BRL",
        "quantity": order.quantity,
        "unit_price": offer["cents"] / 100,
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
    if (result.get("collector_id") is not None
            and str(result["collector_id"]) != expected_collector):
        raise RuntimeError("O checkout retornou um recebedor diferente")
    if not _is_mercadopago_link(checkout_url):
        raise ValueError("Checkout inválido devolvido pelo gateway")
    return checkout_url


def _reconcile_mercadopago_payment(payment_id: str, *, order_id: str = "") -> bool:
    """Only Mercado Pago's authenticated API can set order.status = approved."""
    if not re.fullmatch(r"[0-9]{1,25}", str(payment_id)):
        return False
    data = _mp_request("/v1/payments/" + str(payment_id))
    # Production receipts only: the token prefix does not prove live mode.
    if data.get("live_mode") is not True or str(data.get("id")) != str(payment_id):
        return False
    external_reference = str(data.get("external_reference") or "")
    if not external_reference.startswith("GTECH-"):
        return False
    pid = external_reference.removeprefix("GTECH-")
    if order_id and pid != order_id:
        return False
    # Serialize updates for the same order (including different card attempts).
    order = CheckoutOrder.query.filter_by(id=pid).with_for_update().first()
    if not order:
        return False
    if data.get("currency_id") != "BRL" or str(data.get("collector_id")) != os.getenv("MERCADOPAGO_COLLECTOR_ID", "").strip():
        app.logger.warning("Mercado Pago: recebedor/moeda divergem do pedido %s", pid)
        return False
    try:
        received_cents = Decimal(str(data.get("transaction_amount"))) * 100
        if not received_cents.is_finite() or received_cents != received_cents.to_integral_value():
            return False
    except (InvalidOperation, ValueError, TypeError):
        return False
    if received_cents != order.total_cents:
        app.logger.warning("Mercado Pago: valor divergente no pedido %s", pid)
        return False
    status = str(data.get("status") or "")
    allowed = {"approved", "pending", "authorized", "in_process", "in_mediation", "rejected", "cancelled", "refunded", "charged_back"}
    if status not in allowed:
        return False
    delivery = db.session.get(CheckoutPaymentDelivery, str(payment_id))
    if delivery is not None and delivery.order_id != pid:
        return False
    if delivery is not None and delivery.status == status:
        # Replayed webhook: no new outbox revision or duplicate accounting.
        db.session.rollback()
        return True
    if delivery is None:
        delivery = CheckoutPaymentDelivery(payment_id=str(payment_id), order_id=pid, status=status,
                                           revision=1, delivered_revision=0, attempts=0)
        db.session.add(delivery)
    else:
        delivery.revision += 1
        delivery.status = status
    delivery.updated_at = datetime.utcnow()
    delivery.next_attempt_at = datetime.utcnow()
    db.session.flush()
    payment_statuses = {p.status for p in CheckoutPaymentDelivery.query.filter_by(order_id=pid).all()}
    # A rejected retry must not overwrite another successful payment for the order.
    order.status = next((s for s in ("approved", "in_mediation", "charged_back", "refunded", "in_process", "authorized", "pending", "rejected", "cancelled")
                         if s in payment_statuses), status)
    db.session.commit()
    sync_payment_to_crm(str(payment_id))
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
    if not re.fullmatch(r"(?:[0-9]{10}|[0-9]{13})", ts) or not re.fullmatch(r"[0-9a-fA-F]{64}", v1):
        return False
    # Legacy payment notifications can use seconds; newer notifications use ms.
    # Sign the original header value, but normalize only for the replay window.
    timestamp_seconds = int(ts) / 1000 if len(ts) == 13 else int(ts)
    if abs(time.time() - timestamp_seconds) > 300:
        return False
    manifest = f"id:{payment_id.lower()};request-id:{request_id};ts:{ts};"
    expected = hmac.new(secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.lower(), v1.lower())


# Synchronize one-time SQLite schema bootstrapping across Gunicorn processes.
# PostgreSQL is the required production destination; the lock prevents table
# creation races without wiping or replacing any existing SQLite records.
with app.app_context():
    if db.engine.url.get_backend_name().startswith("sqlite"):
        lock_path = os.path.join(INSTANCE_DIR, "gtech_schema.lock")
        with open(lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                db.create_all()
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    else:
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
    # Chromium applies form-action to the 303 destination after a checkout POST.
    # Only this route needs to navigate to the hosted Mercado Pago checkout.
    form_destinations = "'self'"
    if request.path.startswith("/comprar/"):
        form_destinations += " https://www.mercadopago.com.br https://www.mercadopago.com"
    response.headers.setdefault("Content-Security-Policy", (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        f"form-action {form_destinations}; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; media-src 'self'; connect-src 'self'; frame-src 'none'"
    ))
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if request.path == "/" or request.path.startswith(("/admin", "/pedido/", "/comprar/")) or request.path == "/obrigado":
        response.headers["Cache-Control"] = "no-store, private"
    if request.path.startswith(("/admin", "/pedido/", "/comprar/")) or request.path == "/obrigado":
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
def index(*, form_values=None, form_errors=None):
    if "lead_csrf" not in session:
        session["lead_csrf"] = secrets.token_urlsafe(32)
    return render_template(
        "index.html",
        public_site_url=PUBLIC_SITE_URL,
        contacts=CONTACTS,
        services=SERVICES,
        form_values=form_values or {},
        form_errors=form_errors or {},
        checkout_offers=CHECKOUT_OFFERS,
        nfc_checkout_enabled=_nfc_checkout_enabled(),
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


CRM_SITE_ENDPOINT = "https://web-production-846ce.up.railway.app/api/integrations/site/lead"
CRM_PAYMENT_ENDPOINT = "https://web-production-846ce.up.railway.app/api/integrations/site-payments"
CRM_PRODUCT_MAP = {
    "Placa NFC Personalizada": "nfc",
    "Site Profissional": "site",
    "Perfil da Empresa no Google": "google",
    "Cardápio Digital Premium": "cardapio",
    "Fotos ou Restauração": "foto",
    "Automação ou Sistema": "automacao",
    "Outro serviço": "outro",
}


def sync_lead_to_crm(lead: Lead, city: str) -> bool:
    """Retryable, HMAC-authenticated handoff; local Postgres remains authoritative."""
    delivery = db.session.get(CrmDelivery, lead.id)
    if delivery is None:
        delivery = CrmDelivery(lead_id=lead.id, city=city or "Não informado")
        db.session.add(delivery)
        db.session.commit()
    if delivery.status == "delivered":
        return True
    if os.getenv("CRM_LEAD_SYNC_ENABLED", "false").lower() != "true":
        return False
    endpoint = os.getenv("CRM_LEAD_CAPTURE_URL", "").strip()
    secret = os.getenv("GTECH_SITE_LEAD_SECRET", "").strip()
    if endpoint != CRM_SITE_ENDPOINT or len(secret) < 32:
        app.logger.warning("G Tech: CRM sync disabled, endpoint or secret not approved.")
        return False
    product = CRM_PRODUCT_MAP.get(lead.servico)
    if not product:
        app.logger.warning("G Tech: unknown lead product not synchronized.")
        return False
    mobile = re.sub(r"\D", "", lead.whatsapp)
    if not mobile.startswith("55"):
        mobile = "55" + mobile
    evidence = (ConsentEvidence.query.filter_by(lead_id=lead.id, purpose="budget")
                .order_by(ConsentEvidence.created_at.desc()).first())
    if not evidence or not evidence.terms_version:
        app.logger.warning("G Tech: no consent evidence, cannot export lead to CRM.")
        return False

    details = (
        lead.objetivo + ("\n" + lead.mensagem if lead.mensagem else "")
    )[:900]
    payload = {
        "siteLeadId": lead.id,
        "name": lead.nome,
        "company": lead.negocio,
        "phone": mobile,
        "city": delivery.city,
        "product": product,
        "details": details[:900],
        "consent": True,
        "termsAccepted": True,
        "privacyVersion": evidence.privacy_version,
        "termsVersion": evidence.terms_version,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode("utf-8"), ts.encode("ascii") + b"." + data, hashlib.sha256).hexdigest()
    request_obj = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "X-GTech-Timestamp": ts,
                 "X-GTech-Signature": "sha256=" + digest},
    )
    delivery.attempts += 1
    delivery.updated_at = datetime.utcnow()
    db.session.commit()
    try:
        with urllib.request.urlopen(request_obj, timeout=5) as response:
            result = json.load(response)
            if response.status not in (200, 201) or result.get("ok") is not True:
                raise ValueError("CRM did not confirm handoff")
        delivery.status = "delivered"
        delivery.delivered_at = datetime.utcnow()
        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        app.logger.warning("G Tech CRM sync pending; no lead lost locally. Failure type %s", type(exc).__name__)
        return False


def sync_payment_to_crm(payment_id: str) -> bool:
    """Send an authenticated order hint; CRM independently verifies the payment at MP."""
    if os.getenv("CRM_PAYMENT_SYNC_ENABLED", "false").lower() != "true":
        return False
    secret = os.getenv("GTECH_SITE_LEAD_SECRET", "").strip()
    if len(secret) < 32:
        return False
    delivery = db.session.get(CheckoutPaymentDelivery, payment_id)
    if delivery is None:
        return False
    revision = delivery.revision
    if delivery.delivered_revision == revision:
        return True
    order = db.session.get(CheckoutOrder, delivery.order_id)
    lead = db.session.get(Lead, order.lead_id) if order else None
    evidence = (ConsentEvidence.query.filter_by(lead_id=lead.id, purpose="checkout").first()
                if lead else None)
    if not order or not lead or not evidence or not evidence.terms_version:
        return False
    mobile = re.sub(r"\D", "", lead.whatsapp)
    if not mobile.startswith("55"):
        mobile = "55" + mobile
    payload = {
        "siteOrderId": order.id, "siteLeadId": lead.id, "paymentId": payment_id,
        "externalReference": "GTECH-" + order.id, "amountCents": order.total_cents,
        "currency": "BRL", "payerName": lead.nome, "phone": mobile,
        "productSlug": order.sku, "productTitle": CHECKOUT_OFFERS[order.sku]["title"],
        "quantity": order.quantity, "status": delivery.status,
        "privacyVersion": evidence.privacy_version, "termsVersion": evidence.terms_version,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode("utf-8"), ts.encode("ascii") + b"." + data, hashlib.sha256).hexdigest()
    req = urllib.request.Request(CRM_PAYMENT_ENDPOINT, data=data, method="POST", headers={
        "Content-Type": "application/json", "X-GTech-Timestamp": ts,
        "X-GTech-Signature": "sha256=" + digest,
    })
    delivery.attempts += 1
    attempts = delivery.attempts
    delivery.next_attempt_at = datetime.utcnow() + timedelta(seconds=min(300, 10 * 2 ** min(attempts, 5)))
    db.session.commit()
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            result = json.load(response)
            if response.status not in (200, 201) or result.get("ok") is not True:
                raise ValueError("CRM did not confirm payment")
        # A new webhook received during the request remains pending for its own revision.
        CheckoutPaymentDelivery.query.filter_by(payment_id=payment_id, revision=revision).update({
            "delivered_revision": revision, "delivered_at": datetime.utcnow(),
        })
        db.session.commit()
        return True
    except Exception as exc:
        db.session.rollback()
        app.logger.warning("G Tech payment sync queued (%s)", type(exc).__name__)
        return False


def retry_pending_payments() -> int:
    pending = (CheckoutPaymentDelivery.query.filter(
        CheckoutPaymentDelivery.delivered_revision < CheckoutPaymentDelivery.revision,
        CheckoutPaymentDelivery.next_attempt_at <= datetime.utcnow(),
    ).order_by(CheckoutPaymentDelivery.next_attempt_at).limit(10).all())
    return sum(sync_payment_to_crm(item.payment_id) for item in pending)


def _start_payment_sync_worker():
    if os.getenv("CRM_PAYMENT_SYNC_ENABLED", "false").lower() != "true":
        return
    def run():
        while True:
            with app.app_context():
                try:
                    retry_pending_payments()
                except Exception as exc:
                    db.session.rollback()
                    app.logger.warning("Payment retry worker: %s", type(exc).__name__)
                finally:
                    db.session.remove()
            time.sleep(30)
    threading.Thread(target=run, name="gtech-payment-outbox", daemon=True).start()


@app.get("/api/form-token")
def fresh_lead_form_token():
    """Refresh an expired/stale form token before submitting; never expose credentials."""
    if "lead_csrf" not in session:
        session["lead_csrf"] = secrets.token_urlsafe(32)
    response = app.json.response({"csrf_token": session["lead_csrf"]})
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    return response


@app.post("/lead")
def create_lead():
    if os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview":
        # Preview has disposable storage; do not accept live personal information.
        abort(403)
    token = request.form.get("csrf_token", "")
    expected_token = session.get("lead_csrf", "")
    if not token or not expected_token or not secrets.compare_digest(token, expected_token):
        # Do not weaken CSRF checks. Recover with a fresh session and a clear message,
        # instead of leaving a real customer on the default 400 error page.
        app.logger.warning("G Tech quote rejected: stale_or_missing_csrf (no PII logged)")
        session.pop("lead_csrf", None)
        flash("Sua sessão de segurança expirou. Abra o formulário novamente e reenvie. Nenhum pedido foi cadastrado.", "error")
        return redirect(url_for("index") + "#contato", code=303)
    if request.form.get("website") or request.form.get("form_guard_9"):
        # Password managers sometimes auto-fill inputs named 'website'; keep
        # recognizing legacy submissions but give the customer a safe retry.
        app.logger.warning("G Tech quote rejected: anti_spam_field (no PII logged)")
        flash("Não foi possível validar o formulário. Atualize a página e tente novamente.", "error")
        return redirect(url_for("index") + "#contato", code=303)
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

    allowed_services = {item["form_value"] for item in SERVICES} | {"Outro serviço"}
    allowed_deadlines = {
        "O mais rápido possível", "Em até 7 dias", "Em até 30 dias", "Estou pesquisando"
    }
    field_errors = {}
    if len(nome) < 2:
        field_errors["nome"] = "Informe seu nome com pelo menos 2 caracteres."
    if not valid_phone(whatsapp):
        field_errors["whatsapp"] = "Informe um celular brasileiro válido com DDD e nono dígito. Não aceitamos números de exemplo."
    if servico not in allowed_services:
        field_errors["servico"] = "Escolha um serviço válido."
    if len(objetivo) < 10:
        field_errors["objetivo"] = "Descreva sua necessidade com pelo menos 10 caracteres."
    if prazo not in allowed_deadlines:
        field_errors["servico"] = "Revise as informações do serviço."
    if field_errors:
        # Render the same request with a 422. No personal data is stored in
        # the browser session, database or URL while the form is invalid.
        return index(form_values={
            "nome": nome, "whatsapp": whatsapp, "negocio": clean_text(request.form.get("negocio"), 180),
            "cidade": cidade, "servico": servico, "objetivo": objetivo,
            "consentimento": True, "termos": True
        }, form_errors=field_errors), 422, {"Cache-Control": "no-store, private"}

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
    db.session.add(CrmDelivery(lead_id=lead.id, city=cidade or "Não informado"))
    db.session.commit()
    # Do not fail the customer journey when the CRM integration is unavailable.
    sync_lead_to_crm(lead, cidade)
    return redirect(url_for("thanks"))



@app.route("/comprar/<sku>", methods=["GET", "POST"])
def checkout_product(sku: str):
    if sku not in CHECKOUT_OFFERS:
        abort(404)
    preview_only = os.getenv("RAILWAY_ENVIRONMENT", "").strip().lower() == "preview"
    checkout_enabled = _nfc_checkout_enabled() if sku == "nfc" else _checkout_enabled()
    if request.method == "POST" and not checkout_enabled:
        abort(503)
    offer = CHECKOUT_OFFERS[sku]
    if "checkout_csrf" not in session:
        session["checkout_csrf"] = secrets.token_urlsafe(32)
    if request.method == "GET":
        return render_template("comprar.html", sku=sku, offer=offer, contacts=CONTACTS,
                               csrf_token=session["checkout_csrf"], preview_only=preview_only,
                               checkout_enabled=checkout_enabled,
                               nfc_available=_nfc_available_units() if sku == "nfc" else 0,
                               checkout_intent=_new_checkout_intent(sku))

    token = request.form.get("csrf_token", "")
    if not token or not secrets.compare_digest(token, session.get("checkout_csrf", "")):
        abort(400)
    if (request.form.get("website", "") or request.form.get("consentimento") != "yes"
        or request.form.get("termos") != "yes"):
        abort(400)
    if excessive_lead_submissions(request.remote_addr or "unknown"):
        return Response("Muitas tentativas. Tente novamente mais tarde.", status=429)

    intent = clean_text(request.form.get("checkout_intent"), 200)
    if not _valid_checkout_intent(sku, intent):
        abort(400)
    intent_hash = hashlib.sha256(intent.encode()).hexdigest()
    existing_attempt = _previous_checkout_attempt(intent_hash)
    if existing_attempt is not None:
        return existing_attempt

    name = clean_text(request.form.get("nome"), 100)
    phone = clean_text(request.form.get("whatsapp"), 40)
    quantity = _parse_checkout_quantity(sku, request.form.get("quantity"))
    delivery_confirmed = request.form.get("nfc_local_delivery") == "yes"
    region = clean_text(request.form.get("nfc_delivery_region"), 16) or "local"
    address = {
        "cep": re.sub(r"\D", "", request.form.get("nfc_cep", "")),
        "city": clean_text(request.form.get("nfc_city"), 90),
        "state": clean_text(request.form.get("nfc_state"), 2).upper(),
        "street": clean_text(request.form.get("nfc_street"), 160),
        "number": clean_text(request.form.get("nfc_number"), 20),
        "neighborhood": clean_text(request.form.get("nfc_neighborhood"), 90),
        "complement": clean_text(request.form.get("nfc_complement"), 160),
    }
    values = {"nome": name, "whatsapp": phone,
              "quantity": request.form.get("quantity", "1"),
              "checkout_intent": intent,
              "nfc_local_delivery": delivery_confirmed,
              "nfc_delivery_region": region,
              "consentimento": True, "termos": True, **{"nfc_" + k: v for k,v in address.items()}}
    field_errors = {}
    if len(name) < 2:
        field_errors["nome"] = "Informe seu nome com pelo menos 2 caracteres."
    if not valid_phone(phone):
        field_errors["whatsapp"] = "Informe um celular brasileiro válido com DDD e nono dígito. Não aceitamos números de exemplo."
    if quantity is None:
        field_errors["quantity"] = "Escolha uma quantidade inteira entre 1 e o limite do pedido."
    if sku == "nfc":
        if region != "local":
            field_errors["nfc_delivery_region"] = "Outras cidades e estados exigem cotação prévia de frete. Use Solicitar frete."
        if not delivery_confirmed:
            field_errors["nfc_local_delivery"] = "Confirme que a entrega será em Belém/PA."
        if not re.fullmatch(r"[0-9]{8}", address["cep"]):
            field_errors["nfc_cep"] = "Informe um CEP válido com 8 números."
        if address["state"] != "PA" or address["city"].casefold() not in {"belém", "belem"}:
            field_errors["nfc_city"] = "Pagamento com entrega incluída apenas para Belém/PA. Outras cidades: cotar frete."
        for field, title in [("street", "logradouro"), ("number", "número"), ("neighborhood", "bairro")]:
            if len(address[field]) < 2:
                field_errors["nfc_" + field] = "Informe " + title + " para a entrega."
        if not re.fullmatch(r"[0-9A-Za-zÀ-ÿ .,/-]{2,160}", address["street"]) or len(address["number"]) > 20:
            field_errors["nfc_street"] = "Confira o endereço de entrega."
    if field_errors:
        return _checkout_form_error(sku, offer, preview_only, checkout_enabled, values,
                                    field_errors, session["checkout_csrf"])

    lead = Lead(
        nome=name, whatsapp=normalize_mobile(phone) or phone, negocio="Cliente de checkout",
        servico={"foto": "Fotos ou Restauração", "google": "Perfil da Empresa no Google",
                 "nfc": "Placa NFC Personalizada"}[sku],
        prazo="O mais rápido possível", objetivo="Pedido G Tech: " + offer["title"],
        origem="checkout_gtech"
    )
    order = CheckoutOrder(
        id=str(uuid.uuid4()), lead_id=0, sku=sku, quantity=quantity,
        total_cents=offer["cents"] * quantity, status="pending"
    )
    stock_reserved = False
    persisted = False
    try:
        db.session.add(lead)
        db.session.flush()
        if sku == "nfc":
            # PostgreSQL SELECT FOR UPDATE serializes concurrent buyers.
            inventory = NfcInventory.query.filter_by(id=1).with_for_update().one_or_none()
            if inventory is None:
                initial = _nfc_initial_units()
                if initial < 1:
                    raise NfcStockUnavailable()
                inventory = NfcInventory(id=1, available=initial)
                db.session.add(inventory)
                db.session.flush()
            if inventory.available < quantity:
                raise NfcStockUnavailable()
            inventory.available -= quantity
        order.lead_id = lead.id
        db.session.add(order)
        if sku == "nfc":
            db.session.add(NfcDeliveryAddress(
                order_id=order.id, cep=address["cep"], state=address["state"],
                city=address["city"], street=address["street"],
                neighborhood=address["neighborhood"], number=address["number"],
                complement=address["complement"] or None))
        db.session.add(CheckoutAttempt(token_hash=intent_hash, order_id=order.id))
        db.session.add(ConsentEvidence(lead_id=lead.id, purpose="checkout", privacy_version="2026-11-16", terms_version="2026-11-16"))
        db.session.commit()
        persisted = True
        stock_reserved = sku == "nfc"
        gateway_url = _create_mercadopago_preference(order, offer["title"])
        order.checkout_url = gateway_url
        db.session.commit()
        session["last_checkout_order"] = order.id
        return redirect(gateway_url, code=303)
    except IntegrityError:
        db.session.rollback()
        old = _previous_checkout_attempt(intent_hash)
        if old is not None:
            return old
        app.logger.warning("NFC/checkout: conflict while reserving inventory or nonce")
        return Response("Não foi possível confirmar o pedido. Tente novamente.", 409)
    except NfcStockUnavailable:
        db.session.rollback()
        return _checkout_form_error(sku, offer, preview_only, checkout_enabled, values,
                                    {"quantity": "Estoque insuficiente. Reduza a quantidade ou solicite orçamento."},
                                    session["checkout_csrf"])
    except Exception as exc:
        db.session.rollback()
        app.logger.warning("Mercado Pago: criação indisponível: %s", type(exc).__name__)
        if stock_reserved:
            # A checkout URL was never delivered to the customer.
            # Restore units only for a failed creation; paid/cancelled orders
            # are never restocked automatically without reconciliation.
            try:
                inventory = NfcInventory.query.filter_by(id=1).with_for_update().one()
                inventory.available += quantity
                order.status = "cancelled"
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.error("NFC inventory reservation needs manual review; order %s", order.id)
        # Never show a payment as successful after a gateway error.
        if not persisted:
            return Response("Não foi possível registrar o pedido. Tente novamente.", 503)
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
    deliveries = {x.lead_id: x for x in CrmDelivery.query.filter(CrmDelivery.lead_id.in_([l.id for l in leads])).all()} if leads else {}
    counts = {
        "total": Lead.query.count(),
        "novo": Lead.query.filter_by(status="novo").count(),
        "proposta": Lead.query.filter_by(status="proposta").count(),
        "fechado": Lead.query.filter_by(status="fechado").count(),
    }

    return render_template(
        "admin.html",
        leads=leads,
        deliveries=deliveries,
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


@app.post("/admin/leads/<int:lead_id>/crm-sync")
@requires_auth
def retry_lead_crm(lead_id: int):
    token = request.form.get("admin_csrf", "")
    expected = session.get("admin_csrf", "")
    if not token or not expected or not secrets.compare_digest(token, expected):
        abort(400)
    lead = db.get_or_404(Lead, lead_id)
    delivery = db.session.get(CrmDelivery, lead_id)
    if delivery and delivery.status == "delivered":
        flash("Lead já confirmado no CRM.", "success")
    elif sync_lead_to_crm(lead, delivery.city if delivery else "Não informado"):
        flash("Lead confirmado no CRM G Tech.", "success")
    else:
        flash("CRM não confirmou o recebimento. O contato continua salvo no site.", "error")
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
    base = PUBLIC_SITE_URL
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{base}/</loc></url>"
        f"<url><loc>{base}/privacidade</loc></url>"
        f"<url><loc>{base}/termos</loc></url>"
        "</urlset>"
    )
    return Response(content, mimetype="application/xml")


@app.route("/internal/nfc/stock", methods=["GET", "POST"])
def internal_nfc_stock():
    """Private CRM proxy endpoint: never accessible without a shared S2S secret."""
    secret = os.getenv("GTECH_NFC_STOCK_SECRET", "").strip()
    supplied = request.headers.get("X-GTech-NFC-Key", "")
    if len(secret) < 32 or not hmac.compare_digest(supplied, secret):
        abort(403)
    if not _secure_db_available() and _deployed:
        abort(503)
    if request.method == "GET":
        history = NfcStockMovement.query.order_by(NfcStockMovement.created_at.desc()).limit(20).all()
        # Full addresses are only sent over the private S2S channel to CEO/ADMIN CRM.
        recent = CheckoutOrder.query.filter_by(sku="nfc").order_by(CheckoutOrder.created_at.desc()).limit(25).all()
        orders = []
        for item in recent:
            addr = db.session.get(NfcDeliveryAddress, item.id)
            lead = db.session.get(Lead, item.lead_id)
            orders.append({
                "id": item.id, "status": item.status, "quantity": item.quantity,
                "totalCents": item.total_cents,
                "buyer": lead.nome if lead else "", "phone": lead.whatsapp if lead else "",
                "createdAt": item.created_at.isoformat() + "Z",
                "address": {
                    "cep": addr.cep, "state": addr.state, "city": addr.city,
                    "neighborhood": addr.neighborhood, "street": addr.street,
                    "number": addr.number, "complement": addr.complement or ""
                } if addr else None,
            })
        return {
            "sku": "nfc", "available": _nfc_available_units(),
            "orders": orders,
            "unitPriceCents": CHECKOUT_OFFERS["nfc"]["cents"],
            "maxPerOrder": CHECKOUT_OFFERS["nfc"]["max_quantity"],
            "movements": [
                {"id": h.id, "delta": h.delta,
                 "before": h.available_before, "after": h.available_after,
                 "actor": h.actor, "reason": h.reason,
                 "createdAt": h.created_at.isoformat() + "Z"} for h in history
            ],
        }, 200, {"Cache-Control": "no-store, private"}
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {"error": "JSON inválido."}, 400
    movement_id = payload.get("movementId")
    delta = payload.get("delta")
    reason = payload.get("reason")
    actor = payload.get("actor")
    if (not isinstance(movement_id, str) or len(movement_id) != 36
            or not re.fullmatch(r"[0-9a-f-]{36}", movement_id)
            or type(delta) is not int or delta == 0 or abs(delta) > 500
            or not isinstance(reason, str) or not (8 <= len(reason.strip()) <= 240)
            or not isinstance(actor, str) or not (2 <= len(actor.strip()) <= 100)):
        return {"error": "Movimento inválido; informe quantidade e justificativa."}, 400
    try:
        existing = db.session.get(NfcStockMovement, movement_id)
        if existing is not None:
            return {"ok": True, "available": _nfc_available_units(),
                    "duplicate": True}, 200, {"Cache-Control": "no-store, private"}
        row = NfcInventory.query.filter_by(id=1).with_for_update().one_or_none()
        if row is None:
            row = NfcInventory(id=1, available=_nfc_initial_units())
            db.session.add(row)
            db.session.flush()
        before = row.available
        after = before + delta
        if after < 0 or after > 500:
            db.session.rollback()
            return {"error": "Ajuste excede o estoque disponível ou limite permitido."}, 409
        row.available = after
        db.session.add(NfcStockMovement(
            id=movement_id, delta=delta,
            available_before=before, available_after=after,
            actor=actor.strip(), reason=reason.strip()))
        db.session.commit()
        return {"ok": True, "available": after}, 200, {"Cache-Control": "no-store, private"}
    except IntegrityError:
        db.session.rollback()
        return {"error": "Ajuste concorrente; atualize o estoque antes de tentar novamente."}, 409
    except Exception:
        db.session.rollback()
        app.logger.exception("Falha interna no ajuste de estoque NFC")
        return {"error": "Estoque indisponível. Nenhuma confirmação de ajuste."}, 503


@app.route("/health")
def health():
    return {"status": "ok", "service": "gtech-site-oficial"}, 200


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html", contacts=CONTACTS), 404


_start_payment_sync_worker()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )


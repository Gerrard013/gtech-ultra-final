from __future__ import annotations

import csv
import io
import os
import re
import secrets
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Flask,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
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
        "id": "cardapio",
        "number": "01",
        "title": "Cardápio Digital Premium",
        "form_value": "Cardápio Digital Premium",
        "description": (
            "Uma vitrine mobile para apresentar produtos, promoções e receber pedidos "
            "com muito mais clareza."
        ),
        "benefits": ["QR Code", "WhatsApp integrado", "Categorias e promoções"],
        "icon": "menu",
    },
    {
        "id": "site",
        "number": "02",
        "title": "Landing Page & Site",
        "form_value": "Landing Page ou Site",
        "description": (
            "Presença digital de alto padrão para transformar visitas em conversas, "
            "orçamentos e oportunidades."
        ),
        "benefits": ["Mobile-first", "SEO básico", "Captura de leads"],
        "icon": "rocket",
    },
    {
        "id": "automacao",
        "number": "03",
        "title": "Automação & Sistemas",
        "form_value": "Automação ou Sistema",
        "description": (
            "Soluções sob medida para reduzir tarefas repetitivas, organizar informações "
            "e ganhar produtividade."
        ),
        "benefits": ["Fluxos personalizados", "Painéis", "Banco de dados"],
        "icon": "settings",
    },
    {
        "id": "fotos",
        "number": "04",
        "title": "Fotos & Restauração",
        "form_value": "Fotos ou Restauração",
        "description": (
            "Restauração fiel, melhoria de qualidade e apresentação visual profissional "
            "para memórias e marcas."
        ),
        "benefits": ["Restauração fiel", "Melhoria visual", "Artes digitais"],
        "icon": "image",
    },
]

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
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    return response


def check_auth(username: str, password: str) -> bool:
    expected_user = os.getenv("ADMIN_USER", "gtech")
    expected_pass = os.getenv("ADMIN_PASS", "gtech123")
    return secrets.compare_digest(username, expected_user) and secrets.compare_digest(
        password, expected_pass
    )


def requires_auth(view_func):
    @wraps(view_func)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response(
                "Acesso restrito.",
                401,
                {"WWW-Authenticate": 'Basic realm="G Tech Admin"'},
            )
        return view_func(*args, **kwargs)

    return decorated


def clean_text(value: str | None, max_length: int) -> str:
    return (value or "").strip()[:max_length]


def valid_phone(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return 10 <= len(digits) <= 13


@app.route("/")
def index():
    return render_template(
        "index.html",
        contacts=CONTACTS,
        services=SERVICES,
        feedbacks=FEEDBACKS,
        year=datetime.utcnow().year,
    )


@app.post("/lead")
def create_lead():
    if request.form.get("website"):
        abort(400)

    nome = clean_text(request.form.get("nome"), 120)
    whatsapp = clean_text(request.form.get("whatsapp"), 40)
    negocio = clean_text(request.form.get("negocio"), 180)
    servico = clean_text(request.form.get("servico"), 120)
    prazo = clean_text(request.form.get("prazo"), 120)
    objetivo = clean_text(request.form.get("objetivo"), 2000)
    mensagem = clean_text(request.form.get("mensagem"), 2000)
    origem = clean_text(request.form.get("origem"), 180)

    required = [nome, whatsapp, negocio, servico, prazo, objetivo]
    if not all(required):
        flash("Revise os campos obrigatórios antes de enviar.", "error")
        return redirect(url_for("index") + "#diagnostico")

    if not valid_phone(whatsapp):
        flash("Digite um WhatsApp válido com DDD.", "error")
        return redirect(url_for("index") + "#diagnostico")

    lead = Lead(
        nome=nome,
        whatsapp=whatsapp,
        negocio=negocio,
        servico=servico,
        prazo=prazo,
        objetivo=objetivo,
        mensagem=mensagem,
        origem=origem,
    )
    db.session.add(lead)
    db.session.commit()

    return redirect(url_for("thanks", lead_id=lead.id))


@app.route("/obrigado")
def thanks():
    lead_id = request.args.get("lead_id", type=int)
    lead = db.session.get(Lead, lead_id) if lead_id else None
    return render_template(
        "thanks.html",
        contacts=CONTACTS,
        lead=lead,
        year=datetime.utcnow().year,
    )


@app.route("/admin/leads")
@requires_auth
def admin_leads():
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
    )


@app.post("/admin/leads/<int:lead_id>/status")
@requires_auth
def update_lead_status(lead_id: int):
    lead = db.get_or_404(Lead, lead_id)
    new_status = clean_text(request.form.get("status"), 40)
    if new_status not in STATUS_LABELS:
        abort(400)
    lead.status = new_status
    db.session.commit()
    flash("Status atualizado.", "success")
    return redirect(request.referrer or url_for("admin_leads"))


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
                lead.nome,
                lead.whatsapp,
                lead.negocio,
                lead.servico,
                lead.prazo,
                lead.objetivo,
                lead.mensagem or "",
                lead.origem or "",
                STATUS_LABELS.get(lead.status, lead.status),
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


@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.errorhandler(404)
def not_found(_error):
    return render_template("404.html", contacts=CONTACTS), 404


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )

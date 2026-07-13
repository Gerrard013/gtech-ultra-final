#!/bin/bash
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Criando ambiente virtual..."
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

export SECRET_KEY="${SECRET_KEY:-$(openssl rand -hex 32)}"
export ADMIN_USER="${ADMIN_USER:-gtech}"
export ADMIN_PASS="${ADMIN_PASS:-GTech2026@Local}"

echo ""
echo "G TECH ULTRA FINAL"
echo "Site:   http://127.0.0.1:5000"
echo "Painel: http://127.0.0.1:5000/admin/leads"
echo "Login:  gtech"
echo "Senha:  GTech2026@Local"
echo ""

python app.py

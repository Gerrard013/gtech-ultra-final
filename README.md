# G Tech — Ultra Final

Landing page premium com UI/UX responsiva, interações 3D suaves, prova social real, formulário inteligente de três etapas, banco de dados de leads e painel administrativo.

## O que está incluído

- Design mobile-first e responsivo
- Menu móvel acessível
- Efeitos 3D no desktop e movimento reduzido em dispositivos sensíveis
- Jornada rápida por objetivo
- Serviços com seleção automática no formulário
- Feedbacks reais com recortes sem cabeçalhos pessoais
- Lightbox para ampliar as provas reais
- Formulário em três etapas, sem faixa de investimento
- Validação de WhatsApp e máscara automática
- Rastreamento de origem por UTM
- Banco SQLite local e PostgreSQL no Railway
- Painel com busca, filtros, status, WhatsApp e CSV
- Página de obrigado, 404 e endpoint `/health`

## Rodar localmente no Mac

```bash
cd ~/Desktop/gtech_ultra_final
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
export SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_USER="gtech"
export ADMIN_PASS="GTech2026@Local"
python app.py
```

Acesse:

- Site: `http://127.0.0.1:5000`
- Painel: `http://127.0.0.1:5000/admin/leads`
- Saúde: `http://127.0.0.1:5000/health`

## Deploy no Railway

1. Suba esta pasta para um repositório no GitHub.
2. No Railway, escolha **New Project → Deploy from GitHub Repo**.
3. Adicione um serviço PostgreSQL ao mesmo projeto.
4. Em **Variables**, configure:
   - `SECRET_KEY`
   - `ADMIN_USER`
   - `ADMIN_PASS`
5. O Railway conecta `DATABASE_URL` automaticamente ao vincular o PostgreSQL.
6. Gere o domínio público em **Settings → Networking → Generate Domain**.

## Login do painel local

- Usuário: `gtech`
- Senha: `GTech2026@Local`

No deploy, troque obrigatoriamente a senha pelas variáveis do Railway.

## Rotas principais

- `/` — site
- `/lead` — recebe formulário
- `/obrigado` — confirmação
- `/admin/leads` — painel protegido
- `/admin/export.csv` — exportação
- `/health` — verificação do servidor

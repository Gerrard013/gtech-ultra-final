# G TECH | SITE OFICIAL ÚNICO — Versão 2.0
**Ambiente oficial:** https://gtech-oficial.up.railway.app/  
**Alteração de domínio:** a URL antiga `gtech-ultra-final-production` deixará de funcionar ao renomear o domínio Railway; atualizar todos os links de campanhas, bio e mensagens.  
**Repositório oficial:** \`Gerrard013/gtech-ultra-final\`  
**Status:** versão oficial lançada; integração com CRM em atualização controlada. Pagamentos permanecem desativados até aprovação PJ.

## Objetivo
Unificar a **vitrine pública** da G Tech em um único endereço, mantendo os sistemas privados (CRM completo, gestão de leads, pagamentos e produção) separados tecnicamente.

## O que foi implementado nesta proposta
- Recriação completa da homepage comercial, com identidade dark premium e efeito cinematográfico leve.
- Card hero animado de NFC (com fallback acessível); suporte condicional a vídeo real otimizado.
- Vitrine ampliada para 12 serviços: ofertas originais preservadas e inclusão de e-mail profissional, suporte de TI, redes Wi-Fi, backup, impressão 3D em preparação e conteúdo com IA. Novas ofertas sem checkout direto.
- Fluxos de navegação e orçamento: menu responsivo, CTA de WhatsApp e formulário sem cobrança.
- Cards de portfólio, seção institucional, processo de atendimento, depoimentos já existentes, FAQ e rodapé.
- Fallback sem JS, animações com redução de movimento, suporte mobile, menu teclado e controle de vídeo.
- SEO: title, description, OpenGraph, canonical oficial, dados estruturados Organization, sitemap e robots.
- Formulário mais curto e acessível com validação no cliente **e** no servidor, anti-bot honeypot, consentimento e proteção CSRF.
- Leads continuam no banco local **sem mudanças de schema**, mantendo o admin e CSV existentes.
- Integração **opt-in** com CRM mais recente; desativada por padrão, com whitelist de destino, timeout e fallback local.
- Admin com CSRF no fluxo de mudança de status, headers sem cache, sem senha padrão embutida.
- Política de privacidade inicial e testes de fumaça automatizados.

## Arquitetura real
\`\`\`
Instagram (@gtech_brasil)
         ↓
SITE OFICIAL: gtech-ultra-final-production.up.railway.app
 ├─ Serviços / portfólio / FAQ
 ├─ WhatsApp Business 91 98615-2222
 ├─ POST /lead -> banco próprio existente (backup/resgate)
 └─ Sync CRM opcional (DESATIVADO) -> /api/public/lead
                                        ↓
                       CRM privado gtech-crm-ultra-final
                                        ↓
                              Propostas / IA Council
                                        ↓
                       Checkout validado (etapa posterior)
\`\`\`

**Atenção:** a loja independente e a plataforma antiga não devem ser desligadas ou excluídas agora. Elas podem fornecer código, dados e funcionalidades, mas o site público oficial será este domínio após aprovação e migração segura. Não compartilhar bancos nem chaves de diferentes serviços sem planejamento.

## Mídias reais de cliente
Os seis vídeos foram analisados visualmente. Recomendação: demonstrar NFC na hero e cardápios digitais no portfólio; o vídeo com apresentador só poderá ser utilizado após validar contexto/direitos. Os vídeos **não foram incorporados ao repositório** nesta PR.

Para habilitar o vídeo real no destaque inicial, aprovar, comprimir e incluir manualmente:
\`static/media/hero-nfc.mp4\` — sem trilha não autorizada, muted e playsinline. Enquanto o arquivo não existe, o site usa ilustração animada CSS (não há vídeo quebrado).

As demais cenas podem ser otimizadas para miniaturas e previews, respeitando formatos mobile, lazy loading e permissões de uso.

## Verificar e executar em desenvolvimento
\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export ADMIN_USER="defina-um-usuario-privado"
export ADMIN_PASS="defina-uma-senha-segura-e-unica"
export CRM_LEAD_SYNC_ENABLED="false"
python -m unittest discover -s tests -v
python app.py
\`\`\`
**Nota:** o teste cria SQLite isolado, jamais executa no banco de produção.

## Checklist para liberar a produção
1. Validar preview desktop/mobile, legibilidade e animação.
2. Aprovar preços, escopos, marca, texto e materiais de portfólio.
3. Testar GET /, /privacidade, /health, /sitemap.xml; navegação e formulários sem JS.
4. Enviar lead de teste no staging com autorização; conferir persistência local, consentimento, painel admin e CSV.
5. Conferir em staging a recepção no **CRM correto**; só depois configurar CRM_LEAD_SYNC_ENABLED=true.
6. Inspecionar backups/rollback do banco antigo e alertas de Postgres.
7. Validar quadro de meios de pagamento antes de apresentar 'comprar': **esta versão não cobra automaticamente**.
8. Validar autorização das seis mídias, montar vídeos leves, poster e controle de reprodução.
9. Validar acessibilidade, HTTPS, performance mobile e privacidade com configuração real.
10. Só depois **autorizar merge/deploy**, testar novamente o domínio oficial e alterar o link da bio do Instagram.

## Nota fiscal e limites do MEI
O enquadramento de cada atividade comercial anunciada no CNPJ deve ser verificado antes da contratação/emissão de nota. A existência do MEI não significa que desenvolvimento de software, CRM ou automação esteja automaticamente permitido.

## Operação antiga preservada
- /admin/leads (autenticação exigida)
- /admin/export.csv (autenticação exigida)
- /obrigado (sem mostrar dados pessoais no URL)
- /health
- /privacidade
- /sitemap.xml

Nenhum dado foi migrado, alterado ou excluído.


## Pagamentos diretos da G Tech (revisão de 16/11/2026)
O site oficial usa a API do **Mercado Pago diretamente**, sem intermediar com MetaSimples. O fluxo anterior pelo MetaSimples foi abandonado; a PR do MetaSimples foi encerrada sem merge.

**Fonte única dos preços:** `config/catalogo_gtech.json`
- Editor no GitHub: https://github.com/Gerrard013/gtech-ultra-final/edit/feature/site-oficial-unico-v2-2026-11-13/config/catalogo_gtech.json
- Legendas na vitrine e valores das preferências são lidos desse arquivo.
- `preco_centavos` é número inteiro: 7999 significa R$ 79,99.
- `checkout_direto` deve ficar false para NFC, sites, assinatura, cardápios e automações enquanto não houver condição comercial definida.

**Credenciais exclusivas do serviço G Tech no Railway:** `MERCADOPAGO_ACCESS_TOKEN`, `MERCADOPAGO_WEBHOOK_SECRET`, `MERCADOPAGO_COLLECTOR_ID`. Nunca incluir valores reais no repositório ou chats. `GTECH_CHECKOUT_ENABLED=false` deve continuar false até validação explícita.

O código bloqueia a cobrança caso faltem credenciais, ID do recebedor ou PostgreSQL durável. Além disso, o ambiente preview não recebe pagamentos; nele a página de compra é exclusivamente visual.

**Fluxo:** formulário mobile protegido → pedido persistido no banco G Tech → preferência Checkout Pro no Mercado Pago → Pix/cartão conforme conta recebedora → webhook assinado → consulta autenticada à API → status do pedido. O navegador não pode marcar uma compra como paga só enviando `?retorno=sucesso`.

**ATENÇÃO:** ainda é necessário testar uma transação autorizada e conferir o recebimento real na conta correta. Os testes de GitHub Actions usam resposta simulada do Mercado Pago, nunca dinheiro.

Veja o documento: `docs/PRECOS_E_MERCADO_PAGO_DIRETO_GTECH.md`.

## Integração oficial CRM — HMAC
- Endpoint CRM: `/api/integrations/site/lead` (não é um formulário público).
- Credencial idêntica `GTECH_SITE_LEAD_SECRET` (32+ caracteres) guardada somente nos dois serviços Railway.
- No CRM: `GTECH_SITE_LEAD_ENABLED=true` somente após concluir os testes.
- No site: `CRM_LEAD_SYNC_ENABLED=true`, `CRM_LEAD_CAPTURE_URL=https://web-production-846ce.up.railway.app/api/integrations/site/lead`.
- Somente leads com Termos/Privacidade aceitos seguem para o CRM; dados permanecem no Postgres do site. O admin `/admin/leads` mostra recibo e botão Reenviar ao CRM.
- Não registrar pagamentos como recebidos no CRM pelo envio de orçamento.

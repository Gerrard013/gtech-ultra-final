# G TECH | IA Council — Auditoria de segurança e lançamento
16/11/2026 • Projeto: G Tech | Innovation & Solutions • CNPJ informado: 70.125.976/0001-76

## Regra
Nenhum sistema é invulnerável. Termos de uso NÃO eliminam o direito de processar a empresa. A auditoria técnica reduz riscos e indica provas necessárias; NÃO certifica conformidade integral sem testes reais, avaliação jurídica e inspeção operacional. Site de produção NÃO deve ser modificado sem aprovação expressa.

## Contexto verificado
- Produção: https://gtech-ultra-final-production.up.railway.app/ — branch main (sem deploy nesta revisão).
- Revisão: https://gtech-site-v2-preview-preview.up.railway.app/ — branch de site oficial.
- Railway produção: serviço PostgreSQL online com volume persistente; nome da variável DATABASE_URL presente no serviço web, mas vínculo e teste de restauração ainda não inspecionados.
- Mercado Pago: mudança da conta recebedora CPF → CNPJ solicitada em 16/11, **pendente**. Checkout Pro direto preparado, flag desligada. Nenhuma transação real validada.

## Matriz — ARGOS/NEXO/LUMEN/PRISMA/LEX
| Controle | Evidência | Estado | Próximo requisito |
|---|---|---|---|
| HTTPS/HSTS | Cabeçalhos HSTS condicionados a HTTPS | Parcial | Validar certificado e resposta no domínio oficial |
| CSRF orçamento e checkout | Tokens na sessão e validação de POST | Implementado | Conferir cookies reais em produção |
| Cabeçalhos | X-Frame-Options DENY, CSP com frame-ancestors none, nosniff, COOP/CORP, no-store | Implementado | Scanner HTTPS e revisão CSP de estilos inline |
| Injeção SQL/XSS | ORM SQLAlchemy, Jinja escapando variáveis, scripts locais | Parcial | Scanner e revisão estática de todos os caminhos |
| CSV/planilhas | Fórmulas iniciadas por =, +, - ou @ neutralizadas | Implementado | Testar no programa de planilha real |
| Admin | Credenciais apenas em env, tentativa de adivinhação limitada por IP | Parcial | Exigir MFA externo/Cloudflare Access e limite distribuído em Redis/WAF |
| Formulário | Honeypot, tamanho 1 MB, validação no servidor, rate limit por worker, CSRF | Parcial | Simular abuso e considerar antifraude distribuída |
| WhatsApp | Formato brasileiro validado e exemplos rejeitados | Implementado | Não prova titularidade ou existência: confirmar por mensagem/código se necessário |
| Staging | Campos editáveis; submit apenas demonstrativo, backend não recebe dados reais | Implementado | Teste Playwright e celular real |
| Cookies | Sessão essencial + escolha em cookie próprio por até 180 dias; opção para alterar no rodapé | Implementado | Confirmar persistência/retirada e ausência de rastreadores |
| Privacidade | Página /privacidade, finalidade e direitos LGPD, contato e operadores | Rascunho | Revisão jurídica e conferir práticas reais |
| Termos | Página /termos, escopo, direitos legais, reembolso e terceiros | Rascunho | Revisão jurídica, condições de entrega e publicação de endereço comercial exigível |
| Prova de aceite | Tabela de evidência de consentimento com data, finalidade e versão | Implementado | Testar persistência Postgres real |
| Mercado Pago | Preço do catálogo no servidor, webhook assinado, conferência da API, valor, moeda, referência e recebedor | Simulado | Aprovação PJ, credenciais reais, teste controlado, chargeback/reembolso |
| Dados de cartão | Não solicitados; redirecionamento Checkout Pro hospedado | Projetado | Testar fluxo de Pix/cartão na conta correta |
| Banco de dados | Postgres e volume existentes no projeto de produção | Parcial | Confirmar referência do app, fazer BACKUP + RESTAURAÇÃO comprovados |
| Gerência de segredos | Tokens somente em variáveis backend; checkout flag desativada | Projetado | Rotação, privilégios mínimos e auditoria no Railway |
| Dependências e contêiner | Versões declaradas, testes CI | Parcial | Scanner de vulnerabilidades, Docker usuário não-root e SBOM |
| Vídeos/depoimentos | Conteúdo real fornecido pelo proprietário | Parcial | Confirmar direitos de imagem, áudio, marca e autorização para divulgar feedbacks |
| Tributação e MEI | CNPJ informado | Pendente | Confirmar CCMEI, CNAEs, notas fiscais e contratos conforme serviço |
| Retenção e incidentes | Política e contato previstos | Parcial | Implementar rotina de retenção, registro de incidentes e plano de resposta |
| DAST/pentest | Não realizado | Bloqueado | Revisão de segurança adicional antes de declarar sistema auditado |

## Leis e regras a verificar antes de vender no Brasil
LGPD e regulamentação ANPD aplicável; CDC; regras brasileiras de contratação eletrônica (incluindo Decreto 7.962/2013, conforme aplicável); Marco Civil da Internet; regras fiscais MEI/NFS-e; direitos autorais, marcas, uso de imagem; políticas do Mercado Pago e seus termos de pagamentos. O site não deve ocultar informação obrigatória do fornecedor. Como o proprietário não quer divulgar endereço residencial, definir endereço comercial/correspondência juridicamente adequado antes de vender online.

## Gate de lançamento comercial
1. [x] Retirar bloqueio de digitação da prévia; teste demonstração sem armazenar dados.
2. [x] Cookies de primeira parte, privacidade e termos transparentes no código.
3. [x] Preços centralizados no arquivo de catálogo e cobrança direta pelo site, desativada por padrão.
4. [x] Proteções de formulários, admin e CSV introduzidas nos testes sintéticos.
5. [ ] CI final aprovado, navegação desktop e celular real confirmadas.
6. [ ] Banco app → Postgres confirmado + cópia restaurável.
7. [ ] Cadastro PJ do Mercado Pago aprovado, recebedor e token de produção verificados.
8. [ ] Pagamento controlado e estorno rechecados na API e extrato do recebedor.
9. [ ] Revisão das condições de venda, direitos de imagem e documentos fiscais com profissionais competentes.
10. [ ] Aprovação expressa para GO LIVE, merge e variáveis de Railway.
11. [ ] Depois da liberação do site: CRM G Tech, Instagram e automações.

## Incidentes (guia inicial)
Suspender pagamentos com a flag sem apagar dados; rotacionar segredos; restringir acesso; guardar evidências e logs; verificar pagamentos no provedor, banco e pedidos; avaliar comunicações legais necessárias com orientação especializada; restaurar de backup testado; corrigir a causa antes de reativar.

A palavra FINALIZADO só é usada quando há execução e evidência. Código na branch de revisão não constitui operação comercial ativa.

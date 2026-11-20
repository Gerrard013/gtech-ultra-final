# G TECH — IA Council | SENTINELA: Cibersegurança e Integridade Comercial
Data: 19/11/2026 · Escopo: repositório Gerrard013/gtech-ultra-final, ramo de revisão derivado da correção de formulários.

## Papel institucional
SENTINELA é o novo membro do IA Council, com responsabilidade técnica por segurança de aplicações, prevenção de fraudes, LGPD, exposição de credenciais, estoque e integridade de pagamentos. Pode emitir parecer de bloqueio de publicação por risco crítico. Não substitui auditoria externa, advogados, verificação bancária nem um teste de invasão autorizado. Nenhuma ferramenta garante 100% de invulnerabilidade.

## Inventário observado
- Aplicação Flask 3.0.3 + SQLAlchemy, Gunicorn e PostgreSQL no Railway. Site e banco estavam online na consulta; o serviço PostgreSQL apresentava um alerta sem detalhes suficientes para classificar.
- Web checkout: Mercado Pago Checkout Pro com validação HMAC do webhook, consulta autenticada do ID/valor/moeda/recebedor, CSRF nos formulários e cabeçalhos anti-cache.
- Site oficial permanece em produção na branch main; as mudanças desta revisão estão em PR, não publicadas.
- PR #9 de validação de telefone ainda dependente de revisão; esta branch inclui esse trabalho para não perder dados em caso de erro.

## Achados e recomendações por gravidade
| Gravidade | Achado | Ação nesta revisão | Pendente externo |
|---|---|---|---|
| Alta | NFC sem compra por quantidade e sem controle de estoque no pedido | Preço inteiro em centavos no servidor; máximo por pedido; reserva serializada em tabela separada | Confirmar contagem física e regras de entrega; autorizar GTECH_NFC_SALES_ENABLED |
| Alta | Tokens Mercado Pago divulgados em conversa anterior | Não reutilizar nem imprimir segredos no código | Revogar/rotacionar token, webhook secret, e secret(s) expostos; revalidar app e conta PJ |
| Alta | Controle de acesso Basic Auth do painel sem MFA | Nenhuma mudança de autenticação potencialmente disruptiva nesta PR | Implementar proteção externa com MFA/Zero Trust; revisar compartilhamento de credenciais |
| Alta | Backups de PostgreSQL sem restauração verificada | Nenhuma alteração destrutiva de esquema; nova tabela de estoque isolada | Fazer e comprovar backup + restore, RPO/RTO e procedimentos de incidente |
| Média | Checkout permitia apenas quantidade 1 para produtos | NFC permite 1–8 com cálculo no backend; não confia no total enviado | Teste de compra autorizada de 2–3 unidades e conciliação no CRM |
| Média | Risco de oversell / múltiplas requisições | Lock de estoque em transação DB; não repõe estoque automaticamente em abandono | Reconciliar pedidos abandonados/cancelados antes de liberar reservas; testar concorrência em Postgres |
| Média | Reenvio repetido do mesmo status por webhook | Não duplica revisão do outbox se o status do pagamento já é igual | Observabilidade e alertas de falhas |
| Média | Processo do contêiner rodava como root | Dockerfile revisado para usuário não privilegiado | Validar execução real no Railway |
| Alta | pip-audit identificou vulnerabilidade PYSEC-2026-2151 no Flask 3.0.3 | Atualização proposta para Flask 3.1.3 | Confirmar teste CI, compatibilidade e novo deploy autorizado |
| Média | Rate limit e proteção do admin somente em memória do processo | Nenhuma alteração arriscada sem infraestrutura | Rate limiting distribuído e WAF, validação de proxy e regras de acesso |
| Alta | Chave de sessão ausente ou fraca pode comprometer cookies/CSRF | Falha fechada em deploy se SECRET_KEY tiver menos de 32 caracteres; validação estrita de GTECH_PUBLIC_URL | Validar valor configurado antes de publicar; rotação controlada encerra sessões existentes |
| Média | Envios repetidos de formulário criavam pedidos distintos | Nonce assinado com HMAC, vínculo por sessão e registro único por pedido | Validar disputa concorrente PostgreSQL e logs de gateway |
| Média | Compra física sem cálculo de frete fora de Belém | Restrição explícita a entrega em Belém/PA e aceite | Confirmar política comercial com a equipe e jurídico |
| Média | Dados pessoais e textos legais | Renderização Jinja escapada e resposta 422 no-store | Revisão LGPD, consentimento, prazo de retenção e direitos do consumidor |
| Baixa | SEO/UX e testes de compra | Card NFC na vitrine, resumo de quantidade, teste no navegador | Teste visual manual em celular e notebook |

## Portões para publicação
1. CI e Playwright aprovados, inclusive valores 1× R$79,99, 3× R$79,99 = R$239,97 e limite 8.
2. Confirmar que a PR #9 de correção dos formulários seja incorporada em produção antes deste conjunto, evitando conflitos.
3. Verificar estoque físico, custo da entrega e prazo em Belém/PA. Não usar env de estoque como se fosse um sistema de reposição automática.
4. Conferir aviso do PostgreSQL no Railway e executar restore de backup para ambiente isolado.
5. Rotacionar credenciais vazadas e confirmar conta mercantil correta antes de teste de pagamento real.
6. Teste autorizado de Pix e cartão com comprador independente; validar entrega de webhook, status e idempotência no CRM.
7. Auditar reembolso/chargeback, reconciliação e estoque reservado antes de colocar NFC no ar.
8. Aprovação visual e operacional do fundador. Não executar merge/deploy automaticamente.

## Regras permanentes do SENTINELA
- Segredo só no cofre de variáveis do servidor. Nunca no navegador, logs, repositório ou conversa.
- Valor e estoque são determinados pelo servidor, não pelos campos HTML.
- Pedido com pagamento "pending" nunca significa venda confirmada.
- Não anunciar auditoria como certificação, conformidade integral ou "site inviolável".
- Monitorar avisos de infraestrutura, implementar relatórios de vulnerabilidade e retestar após qualquer mudança.

# Pagamento no site e controle no CRM

O site oficial (`https://gtech-oficial.up.railway.app`) cria o pedido e abre o Checkout Pro. Mercado Pago processa o pagamento. O CRM recebe o pedido, consulta novamente o pagamento na API autenticada e registra os valores financeiros.

## Entrega persistente

- Cada pagamento verificado é salvo em `gtech_checkout_payment_deliveries`, na mesma transação que atualiza o pedido.
- O site envia `POST /api/integrations/site-payments` no CRM, com HMAC SHA-256 sobre `timestamp + '.' + corpo JSON`. Usa o mesmo `GTECH_SITE_LEAD_SECRET` da integração de contatos.
- O CRM confirma com `{ "ok": true }`. Falhas permanecem no banco, com tentativas automáticas a cada 30 segundos e intervalo progressivo de até 5 minutos por registro.
- Cada nova atualização, inclusive estorno, incrementa a revisão pendente. Uma resposta atrasada não confirma a revisão mais recente por engano.
- O CRM valida ID, referência, valor, moeda e recebedor pela API Mercado Pago. O corpo enviado pelo site nunca é prova de pagamento.
- O Financeiro registra receita e taxa em lançamentos distintos, sem duplicar o mesmo pagamento. Data de disponibilidade, parcelas e líquido ficam no registro de conciliação.

## Configuração

No site: `CRM_PAYMENT_SYNC_ENABLED=true`. No CRM: `GTECH_SITE_PAYMENT_ENABLED=true`. As credenciais Mercado Pago, recebedor e confirmação PJ precisam ser validados nos serviços antes de habilitar cobranças reais. Segredos ficam nos servidores.

Webhook do site: `https://gtech-oficial.up.railway.app/webhooks/mercadopago`.

Não basta preencher variáveis para considerar a entrega aceita: falta comprovar checkout e conciliação com credenciais da conta G Tech. Os testes locais usam pagamentos simulados e banco isolado, sem cobrança real.

## Compatibilidade

A aplicação usa Checkout Pro / API de Preferences, compatível com o código existente. Em 16/11/2026, o painel Mercado Pago exibe aviso de futura descontinuação dessa API. A migração para Orders deve ser tratada separadamente, com nova validação completa do fluxo.

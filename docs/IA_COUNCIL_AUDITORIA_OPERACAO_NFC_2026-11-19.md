# G Tech — IA Council | Auditoria operacional e logística NFC
Data: 19/11/2026 · Conselho: SENTINELA (segurança), ATLAS (operações e logística), ÍRIS (UX/CX), MERCÚRIO (checkout/finanças), PULSO (CRM e automações).
Escopo verificado: repositórios do site e CRM G Tech, registros Railway, checkouts de NFC, estoque, fila de pedidos e interface administrativa.
**Não é pentest, certificação de segurança ou inspeção física de transportadoras.**

## Diagnóstico confirmado no código/ambiente
1. Endereço já era salvo no PostgreSQL do site junto ao pedido NFC, mas a interface do CRM o ocultava enquanto o pagamento estava pendente. A API já enviava endereços somente por canal autenticado S2S.
2. Pedidos chegavam no CRM sem prioridade operacional, status de preparação/entrega, referência de motorista ou trilha de alterações logísticas.
3. As reservas NFC são descontadas no momento da criação do checkout. Pedidos abandonados/pendentes podem ocupar estoque por prazo indeterminado. **Não liberar reserva automaticamente** sem reconciliação financeira do gateway.
4. O preço anunciado em Belém/PA inclui entrega, mas o custo por bairro, distância e deslocamento não está parametrizado. Sem dados de custos, não é possível afirmar margem real.
5. Outros estados recebem cotação via WhatsApp antes do pagamento; não há integração ativa de Correios/Melhor Envio e ainda faltam peso/embalagem/CEP origem e regra de prazo. Não inventar frete.
6. O Mercado Pago é autoridade para status do pagamento: retorno do navegador e contato comercial não são comprovante.
7. O status de pedido anteriormente priorizava um pagamento aprovado sobre indicadores de chargeback/estorno no caso de tentativas mistas. Revisão conservadora passa a bloquear o processo para conferência humana.
8. O banco do site possui API interna S2S, mas a chave é oculta no Railway. A operação só pode ser considerada integrada após um usuário CEO/ADMIN conferir efetivamente a leitura da fila no CRM.
9. Logs Railway mostraram checkout NFC redirecionando com HTTP 303 após correção do HTTP 409 anterior; isso não equivale a compra paga.
10. Endereços pessoais são tratados como dados privados e exibidos apenas a CEO/ADMIN. Não os colocar em URL pública, logs ou automações sem necessidade.

## Alterações desta revisão
- `NfcFulfillment`: estado operacional separado do status bancário, prioridade administrativa e referência local/rastreamento.
- `NfcFulfillmentEvent`: histórico imutável por alteração, identificador de ação idempotente e motivo obrigatório.
- Etapas: não iniciado → preparando → pronto → saiu para entrega → entregue; desvio `on_hold` para revisão.
- Pagamento não aprovado, endereço ausente ou referência ausente impedem etapas de envio. Refund/chargeback/disputa têm prioridade máxima de análise.
- API privada de leitura da fila (até 100 pedidos recentes) agrega endereço, status de pagamento, prioridade calculada, estado logístico e razão de triagem. Sem número de telefone/endereço em logs.
- Consulta privada de histórico por pedido. CRM só expõe endpoints a CEO/ADMIN autenticados e com CSRF para mutações.
- Tela CRM prioriza pedidos urgentes e pagos, mostra endereço mesmo antes do pagamento para conferência, mas avisa para não preparar/entregar até `approved`.
- A fila atualiza quando visível e permite confirmar alterações de forma manual, sem disparar mensagens externas.

## Checklist real para entrega
1. Verificar que o pedido e o endereço foram recebidos no CRM (e que não aparecem a perfis sem acesso).
2. Conferir que o Mercado Pago registrou `approved` no servidor, sem apenas confiar no retorno do navegador.
3. Conferir número de plaquinhas reservadas no estoque físico e a personalização NFC solicitada.
4. Conferir CEP, logradouro, número, bairro, telefone e condições locais antes de montar rota.
5. Calcular custo real da entrega local e precificar frete interestadual previamente, incluindo embalagem.
6. Registrar preparo, conferência, entregador/referência, saída, comprovante de entrega e pós-venda.
7. Se pagamento estiver pendente >24h, recusado ou contestado, investigar e conciliar antes de liberar reserva ou despachar.

## Pendências externas e riscos que impedem declarar o sistema totalmente homologado
- Confirmar conexão S2S no CRM por login de CEO/ADMIN, pois variáveis privadas não são legíveis pela integração.
- Validar webhook Mercado Pago com uma compra autorizada, conciliar ID, valor, recebedor, estorno e idempotência.
- Documentar política de expiração de reservas e conciliação manual de pagamentos abandonados; não fazer devolução automática de estoque sem conferência.
- Definir SLA de preparação e entrega por área, custo de transporte e política de devolução.
- Formalizar privacidade/LGPD, prazo de retenção de endereços, solicitação de exclusão e acesso a histórico.
- Implementar integração de frete quando houver fornecedor, peso real, medidas e CEP de origem verificados.
- O backlog de pedidos nesta versão limita-se aos 100 mais recentes; adicionar paginação antes de escalar volume.
- Não há comunicação automática ao cliente, integração com emissão de NF, rastreamento por transportadora nem prova de recebimento digital.

## Princípios de publicação
Site primeiro; CRM depois. Testes CI obrigatórios. Nenhuma cobrança sintética ou alteração de pedidos reais. Manter as credenciais no Railway. Publicação pode ser interrompida por qualquer falha de compilação, regressão ou risco operacional.

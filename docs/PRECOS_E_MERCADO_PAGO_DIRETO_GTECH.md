# G TECH — Painel de preços e Mercado Pago direto

Atualizado em 16/11/2026. **Não usa MetaSimples**. O catálogo em `config/catalogo_gtech.json` é a fonte única de preços do site e dos pagamentos.

## Links operacionais
- **Abrir/editar valores no GitHub:** https://github.com/Gerrard013/gtech-ultra-final/edit/feature/site-oficial-unico-v2-2026-11-13/config/catalogo_gtech.json
- **Arquivo para conferência:** https://github.com/Gerrard013/gtech-ultra-final/blob/feature/site-oficial-unico-v2-2026-11-13/config/catalogo_gtech.json
- **Código do checkout (revisão):** https://github.com/Gerrard013/gtech-ultra-final/pull/1
- **Painel oficial de apps Mercado Pago:** https://www.mercadopago.com.br/developers/panel
- **Site G Tech staging:** https://gtech-site-v2-preview-preview.up.railway.app/
- **Site de produção (não alterar sem autorização):** https://gtech-ultra-final-production.up.railway.app/

## Como atualizar um preço
Abra o link de edição do JSON. Altere os números do campo `preco_centavos` e o texto do campo `preco_exibicao` do mesmo produto. Ex.: R$ 79,99 = `7999`; R$ 150,00 = `15000`. Se o produto está sob orçamento, não preencha `preco_centavos` e mantenha `checkout_direto=false`. Confira o valor no navegador após o build da PR; a edição de uma branch não muda a produção até passar pelo merge/deploy autorizado.

### Situação dos produtos no catálogo
| Produto | Valor base | Compra direta agora? |
|---|---:|---|
| NFC | R$ 79,99 | NÃO: depende de estoque, frete e entrega |
| Criação de site | a partir de R$ 500 | NÃO: escopo sob proposta |
| Google Perfil da Empresa | R$ 150 | Pode ser configurado após aprovação do gateway |
| Cardápio | Sob orçamento | NÃO |
| Restauração básica de foto | a partir de R$ 10 | Pode ser configurada após aprovação do gateway |
| Automações | Sob orçamento | NÃO |
| Manutenção tradicional do site | R$ 149,99/mês | NÃO: falta contrato e mecanismo de assinatura |
| Site sem setup promocional | R$ 129,99/mês | NÃO: compromisso 12 meses, contrato e assinatura |

**Atenção:** os dois planos mensais não estão implementados como cobranças recorrentes. O Checkout Pro atual é para pagamentos únicos.

## Chaves do Mercado Pago: somente G Tech Railway
É preferível criar uma aplicação dedicada G Tech no painel de desenvolvedor do Mercado Pago. Tokens nunca vão no GitHub, em chat ou no navegador. No Railway do serviço oficial, configurar:
- `MERCADOPAGO_ACCESS_TOKEN`: chave **de produção** da conta G Tech, somente backend.
- `MERCADOPAGO_WEBHOOK_SECRET`: segredo de assinatura obtido em notificações webhooks do app.
- `MERCADOPAGO_COLLECTOR_ID`: ID do vendedor/recebedor da **mesma conta** G Tech Mercado Pago.
- `GTECH_CHECKOUT_ENABLED=false`: manter desligado até aprovação.

Webhook de produção para registrar no Mercado Pago após publicar código seguro: `https://gtech-ultra-final-production.up.railway.app/webhooks/mercadopago`

## Critérios bloqueantes de venda real
- Confirmar CNPJ/CPF recebedor em produção, token, collector id, política de estornos e emissão fiscal do MEI.
- Confirmar PostgreSQL persistente com backup restaurável. O código recusa checkout com SQLite ou sem as variáveis exigidas.
- Testar aprovação, pendência, pagamento parcial, assinatura falsa, reembolso e chargeback com a API.
- Validar idempotência de preferências e webhook, segurança do formulário/CSRF e preços do catálogo.
- Executar um pagamento controlado quando expressamente autorizado pelo proprietário, conferindo o extrato real do recebedor. Sem a transação não se declara que o fluxo já recebeu dinheiro.
- Merge/deploy apenas com autorização final.

## IA Council
**NEXO:** implementação/API. **ARGOS:** segurança e autenticidade de webhook. **PRISMA:** preços, taxas e margem. **VÉRTICE:** jornada de compra. **AURORA:** gate de produção.

## Status atual
Logo do cabeçalho corrigida no CSS da branch. Catálogo e rota diretos preparados; testes sintéticos em execução. MetaSimples PR #1 foi **fechada sem merge/deploy** para não criar arquitetura concorrente. Nenhuma credencial ou cobrança alterada.

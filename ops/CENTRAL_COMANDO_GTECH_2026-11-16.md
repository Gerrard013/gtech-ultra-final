> **DECISÃO MAIS RECENTE — 16/11/2026:** Mercado Pago DIRETO no site G Tech. MetaSimples NÃO será intermediário; todas as referências anteriores neste histórico à ponte MetaSimples foram SUPERADAS. O preço oficial está em `config/catalogo_gtech.json`; veja `docs/PRECOS_E_MERCADO_PAGO_DIRETO_GTECH.md`. Cobranças em produção permanecem DESLIGADAS até validar conta recebedora, banco, webhook e preço.

# G TECH | CENTRAL DE COMANDO — 16/11/2026
**CEO:** Gerrard Costa Maciel  
**Marca:** G Tech | Innovation & Solutions  
**CNPJ informado:** 70.125.976/0001-76 (situação fiscal/CCMEI não reconsultada neste documento)  
**Canal oficial de venda:** (91) 98615-2222  
**SITE OFICIAL (produção preservada):** https://gtech-ultra-final-production.up.railway.app/  
**PR de preparação (NÃO mesclada):** https://github.com/Gerrard013/gtech-ultra-final/pull/1  
**STAGING para revisão:** https://gtech-site-v2-preview-preview.up.railway.app/

## Regra do IA Council
Uma fase de cada vez. É permitido melhorar código e executar testes em branch/staging; **nenhum merge, deploy no domínio oficial, mudança de pagamento ou publicação em rede social sem autorização expressa**. Toda tarefa deve ter (i) ação, (ii) prova, (iii) pendências, (iv) responsável e (v) aceite.

## Estado confirmado em 16/11/2026
| Trilha | Situação | Prova | Bloqueio |
|---|---|---|---|
| Formalização MEI | Informada como concluída | CNPJ fornecido anteriormente | Conferir CCMEI, ocupações e adequação fiscal das ofertas |
| Site: identidade/UX | Prévia implantada | Railway staging SUCCESS; PR GitHub draft | Aprovação final do CEO, backup e plano de rollback |
| Vídeos | Quatro MP4 próprios presentes | `static/media/belem-studio-nfc.mp4`, `nfc-demo.mp4`, `cardapio-demo.mp4`, `hero-nfc.mp4` | Validação subjetiva em aparelhos reais, consentimento de uso e licença |
| Abertura | 3,4s, botão Pular/Rever | Código JavaScript + teste visual | Conferir se experiência ao retornar é adequada para clientes |
| Formulário | Testes sintéticos passam | CSRF, consentimento, heurística de número e rate limit em memória | Validar persistência real/backup em produção e proteção distribuída |
| Cookies/privacidade | Banner essencial/opcional presente | JS localStorage, política e testes visuais | Revisão jurídica da política e não ativar rastreadores antes do consentimento |
| CRM / IA Council | Código e API existentes em outro projeto | `gtech-crm-ultra-final`, endpoint `/api/public/lead` | Dados sintéticos de integração real em staging; deduplicação, webhook, resilência; bandeira off até aceite |
| Pagamentos | NÃO LIBERADO | Nenhum checkout desta PR | Validar fornecedor do gateway, recebedor, Pix/cartão, webhooks, contratos/renovações |
| Instagram @gtech_brasil | Nome/bio aprovados anteriormente | Observado em auditoria anterior | Verificar configuração atual e só trocar link após lançamento |
| WhatsApp Business | Número comercial definido | +55 91 98615-2222 | Verificar perfil/catálogo, etiquetas, resposta e confirmação do canal |
| Automação de vídeo/publicação | Arquitetura discutida | repos/skills estudadas | Sistema ainda não implantado, publicação depende de conector autorizado |
| Impressora 3D | Compra em pesquisa | Aguardando respostas de fornecedor | Comparar ofertas reais e preservar caixa; não presumir valor ou prazo |

## Conselho de IA — decisões
**Tecnologia/Segurança:** manter CRM sync opt-in (variável `CRM_LEAD_SYNC_ENABLED=false`). Os testes introduzidos nesta PR não enviam rede: fazem mock da API e confirmam preservação local em falha. A proteção de abuso in-memory **não é suficiente** para replicação horizontal ou tráfego elevado. 
**Comercial:** CTAs de WhatsApp podem captar interessados imediatamente; não exibir “comprar agora” sem checkout confirmado. A página já informa ofertas e valores indicativos.
**Financeiro:** os preços `site R$ 500 + manutenção R$ 149,99/mês` e a campanha anterior `site R$ 129,99/mês sem setup` são produtos/condições diferentes; decidir contrato, carência e custos antes do gateway. Não reservar caixa da rescisão para despesas fixas sem previsão de retorno. 
**Fiscal:** MEI e CNAE precisam ser conferidos antes de emitir nota de atividades de tecnologia, desenvolvimento ou consultoria. 
**UX/mobile:** o vídeo `IMG_1144.mov` é a apresentação em Belém Studio/Batista Campos e aparece como Vídeo 1. Sem iframe/Drive. A página mobile passou em teste automatizado; falta conferência em aparelho do usuário. 
**Operações:** publicar domínio oficial só após validar banco persistente e rotina de backup/rollback; serviço Railway mostra `DATABASE_URL` mas não expõe o tipo de banco pelos metadados, e não há volume montado no próprio serviço.

## Etapas e gates
### Etapa A — finalizar site (AGORA)
- [x] URL oficial única decidida
- [x] Logo oficial, feedbacks reais e quatro vídeos próprios no código da PR
- [x] Site preview no Railway online
- [x] Testes de mobile, anti-spam, cookies, vídeo, formulários isolados
- [x] Testes **simulados** de compatibilidade CRM (sem rede real) adicionados à PR
- [ ] Conferir CI após testes de integração simulados
- [ ] Revisão final no celular real do proprietário
- [ ] Confirmar tipo do banco de produção, backup e rollback
- [ ] Aprovação explícita de GO LIVE — SEM pagamento automatizado
### Etapa B — Instagram
- [ ] Confirmar bio/destaques atuais e corrigir links para domínio oficial apenas após aceite
- [ ] 3 posts fixos: serviços, prova real (Belém Studio), NFC
- [ ] Conectar Metricool se o proprietário desejar agendamento
### Etapa C — WhatsApp
- [ ] Perfil + catálogo + respostas rápidas + etiquetas
- [ ] Confirmar conexão com CRM, sem vincular o número a Cloud API até decisão de custo
### Etapa D — CRM / IA Council
- [ ] Definir instância CRM definitiva
- [ ] Testar integração em staging com dados sintéticos e autorização
- [ ] Habilitar sincronização com CRM só após verificar deduplicação/recuperação
- [ ] Painel de funil, equipe, fornecedores, permissões e acompanhamento de propostas
### Etapa E — Pagamentos
- [ ] Aprovar catálogo e tabela de preços por modalidade
- [ ] Confirmar PagBank/Mercado Pago como recebedor
- [ ] Pix/cartão, webhook assinado, conciliação, cancelamento, reembolso e NF
- [ ] Testar compra completa antes do botão “Comprar”
### Etapa F — Marketing/IA
- [ ] Design de conteúdo e skills, corte/transcrição/video
- [ ] Calendário editorial com aprovação IA Council
- [ ] Conectar publicação Instagram/Meta a uma conta autorizada
### Etapa G — Operação de vendas
- [ ] Planejar oferta de 8 tags NFC já disponíveis
- [ ] Qualificar prospects, registrar contatos no CRM, confirmar condições e nota
- [ ] Controle de margem por serviço, caixa e atendimento pós-venda
- [ ] Escolha e compra da impressora 3D apenas após comparar propostas e garantia

## Impressora 3D — critérios de comparação quando fornecedores responderem
Coletar: modelo exato (ex. A1 Combo, não A1 mini), condição nova/lacrada, garantia em NF, preço final com entrega a Belém, acessórios incluídos (AMS Lite se Combo), voltagem/tomada, prazo, política de devolução, instalação, atendimento e custo do filamento. Mercado Livre vs loja física: mesma cesta de itens e custo total, não preço de anúncio isolado. **Não alegar preço atual sem evidência.**

## Próxima ação imediata
1. Rodar CI da PR após incluir testes sintéticos do CRM e registrar resultado.
2. Fazer auditoria de preservação de dados/backup e revisão mobile final.
3. Apresentar GO LIVE sem cobrança automática para autorização do CEO — e somente então publicar.
4. Passar ao Instagram e WhatsApp enquanto se prepara o checkout sandbox.

O propósito do plano é faturar com segurança, não executar 100 alterações sem critérios de aceite.

## Atualização — Gateway Mercado Pago + CRM, 16/11/2026
**Código preparado, não implantado na produção.**
- Site oficial, PR #1: Checkout Pro com formulário mobile, proteção CSRF, valores no servidor, ponte autenticada para MetaSimples e página de status que não confia no retorno do navegador.
- MetaSimples, PR #1: correção da liberação insegura por status da URL; ponte HMAC no endpoint /api/gtech/checkout; pedidos próprios, verificação da assinatura de webhook e reconciliação de valor, moeda e status exclusivamente pela API Mercado Pago.
- CRM, PR #16: nomes AURORA (orquestração), VÉRTICE (vendas), PRISMA (financeiro), ARGOS (segurança), com NEXO, LUMEN, ÓRBITA e LEX documentados; aceita cardápio e automação como orçamento sem atribuir preço fictício.
- Checkout desativado por padrão até que o CEO e o responsável técnico validem recebedor real, credenciais, armazenamento durável, conta bancária, webhook e termos fiscais. Site usa GTECH_CHECKOUT_ENABLED; MetaSimples usa GTECH_STORE_CHECKOUT_ENABLED.
- Preços fixos no servidor: foto R$10 e Google R$150 (links de compra preparados); NFC R$79,99 aguarda frete/estoque; site R$500 requer proposta; manutenção R$149,99/mês NÃO está configurada como assinatura automática.
- WhatsApp: aba conectada apresenta Maker Blue 3D Fornecedor, grupo Tá em Oferta #3D 20 e Rodrigo Impressao 3D, mas apenas prévias das conversas são legíveis até o usuário abri-las. Não confiar na promessa irrestrita de reembolso pelo Mercado Livre.
- A compra de Bambu Lab A1 precisa diferenciar versão regular e Combo com AMS Lite; conferir vendedor, NF, garantia, preço final no cartão, frete, proteção da plataforma e nenhum pagamento externo.

### Gates obrigatórios antes do fluxo real
1. Confirmar backup/restauração e conexão durável do banco de leads do site.
2. Confirmar que a conta Mercado Pago recebedora e credenciais de produção pertencem à empresa desejada.
3. Configurar segredo compartilhado forte e idêntico nos dois serviços Railway; não compartilhar em chat/repositório.
4. Testar webhook e pagamento, sem usar status de URL como prova; validar Pix/cartão, cancelamentos e reembolsos.
5. Conferir catálogo, estoque/frete, enquadramento MEI, condições de prestação e notas fiscais.
6. Aprovar explicitamente merge/deploy, flags, Instagram e cobrança.

### Ordem de execução mantida
SITE + CRM + MERCADO PAGO -> Instagram -> vídeos/posts e programação -> WhatsApp Business -> impressão 3D como compra financeira em paralelo.

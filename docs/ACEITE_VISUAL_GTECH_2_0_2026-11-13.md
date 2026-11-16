# G Tech 2.0 — Entrega visual para aprovação
**Data:** 13/11/2026  
**Ambiente de revisão:** https://gtech-site-v2-preview-preview.up.railway.app/  
**Site oficial que NÃO deve ser alterado sem autorização:** https://gtech-ultra-final-production.up.railway.app/

## Quatro ajustes solicitados — implementados na branch
1. **Logo verdadeira na abertura.** O arquivo original `static/assets/gtech-logo.png` foi conferido visualmente com a imagem oficial enviada. A imagem é exibida integralmente, sem alterar cores, escudo, G, órbita ou assinatura `Innovation & Solutions`. Partículas da abertura são amostradas dos próprios pixels do arquivo, dispensando letras artificiais. Botão Pular e Rever; animação 3,4 s e respeito ao movimento reduzido.
2. **Tipografia coerente com a marca.** O lettering exato continua sendo o que está DENTRO da arte original. Para títulos editáveis (não reproduções do desenho da marca), usar Oxanium; para textos de leitura e botões, Manrope, com fallback de sistema.
3. **Portfólio real.** A seção artificial com hambúrguer foi removida. NFC real, cardápio real e plaquinhas NFC são demonstrados via vídeos do proprietário no ambiente isolado. Os três players do Drive só carregam após o clique; se uma permissão impedir o acesso, o link para o vídeo original permanece.
4. **Prova social original.** As duas capturas já existentes `static/assets/feedback-nilse.webp` e `static/assets/feedback-sara.webp` voltaram ao site, acompanhadas dos trechos de depoimentos que existiam na página antiga, após a seção de projetos.

## Melhoria comercial também incluída
- H1 explícito: sites, NFC e serviços para destacar empresas.
- Title pesquisável `G Tech Belém | Plaquinhas NFC, Sites e Google Maps`.
- Seis serviços com preço de referência/consulta, CTA para orçamento e WhatsApp oficial (91) 98615-2222.
- Desktop, mobile, acessibilidade, SEO básico e fluxo de orçamento já codificados na branch anterior.
- O formulário está bloqueado no ambiente `preview` para NÃO recolher dados pessoais em banco temporário.
- Integração com CRM opcional e desativada até testes. NÃO existe cobrança no novo site nesta revisão.

## Observações que impedem publicar diretamente em produção
- **Vídeos:** três MP4 comprimidos estão no pacote externo `GTECH_SITE_2_MIDIAS_OTIMIZADAS.zip` e precisam ser hospedados no serviço/objeto de mídia próprio após confirmação dos direitos e upload. Os players Drive do staging são temporários e podem exigir login.
- **CRM:** testar cadastro ponta a ponta, mapping, tratamento de duplicatas, dados de consentimento e proteção de privacidade antes de ativar.
- **Checkout:** validar credenciais oficiais, recebedor, Pix/cartão, webhook assinado, conciliação, cancelamentos e teste sandbox; NÃO criar botão de cobrança antes de confirmação.
- **Operação:** backup do banco existente, plano de retorno, aprovação expressa do proprietário para merge e deploy.
- **MEI:** conferir adequação fiscal dos serviços anunciados antes de nota/contratação, sem presumir CNAE permitido.

## Portões de aceite
- [x] Ajustes visuais codificados e testados em branch/staging.
- [x] Duas capturas de feedback existentes reutilizadas e testadas em navegador.
- [x] Nova abertura com logo oficial e partículas, com controles de acessibilidade.
- [x] Seção de portfólio baseada em mídias de origem e não ilustrações fictícias.
- [ ] Aprovação visual do proprietário.
- [ ] Hospedagem definitiva dos arquivos MP4 e teste de reprodução independente de Drive.
- [ ] Teste real de integração CRM em staging com dados sintéticos.
- [ ] Testes de checkout e meios de pagamento.
- [ ] Autorização explícita de produção.

A PR é **draft**, não deve ser mesclada, e a produção segue na versão de setembro de 2026.

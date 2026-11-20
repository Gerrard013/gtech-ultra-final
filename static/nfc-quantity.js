/* G Tech NFC: UI-only amount preview. The server owns stock, price, and quantity. */
(() => {
  "use strict";
  const form = document.getElementById("checkout-form");
  const quantity = document.getElementById("nfc-quantity");
  const total = document.getElementById("nfc-total-price");
  const summary = document.getElementById("nfc-quantity-summary");
  if (!quantity || !total) return;
  const chat = document.getElementById("nfc-whatsapp-order");
  const chatBase = chat?.href || "";
  const region = document.getElementById("nfc-shipping-region");
  const cep = document.getElementById("nfc-dest-cep");
  const city = document.getElementById("nfc-dest-city");
  const state = document.getElementById("nfc-dest-state");
  const quote = document.getElementById("nfc-nationwide-quote");
  const localAddress = document.getElementById("nfc-local-address");
  const localConfirmation = document.getElementById("nfc-local-confirmation");
  const submit = form?.querySelector("button[type=submit]");
  const checkoutNotice = document.getElementById("nfc-delivery-notice");
  const isNational = () => region?.value === "national";
  const cents = Number(total.dataset.unitCents);
  if (!Number.isSafeInteger(cents) || cents < 1) return;
  const minimum = Number(quantity.min || "1");
  const maximum = Number(quantity.max || "1");
  const money = new Intl.NumberFormat("pt-BR", {style:"currency", currency:"BRL"});
  const update = () => {
    const count = Number(quantity.value);
    const valid = Number.isSafeInteger(count) && count >= minimum && count <= maximum;
    if (valid) {
      total.textContent = money.format(count * cents / 100);
      if (summary) summary.textContent = count === 1 ? "1 unidade" : count + " unidades";
      if (chat) {
        const link = new URL(chatBase);
        const description = count === 1 ? "1 plaquinha NFC" : count + " plaquinhas NFC";
        const destination = isNational() ? "Destino: " + (city?.value || "não informado") + "/" + (state?.value || "?") + ", CEP " + (cep?.value || "não informado") + ". Solicito cotação de frete antes do pagamento." : "Entrega em Belém/PA. Endereço completo será informado de forma privada na confirmação.";
        link.searchParams.set("text", "Olá! Quero consultar a compra de " + description + ". Valor dos produtos: " + money.format(count * cents / 100) + ". " + destination + " Podem confirmar o estoque e o valor final?");
        chat.href = link.toString();
        chat.removeAttribute("aria-disabled");
        chat.textContent = isNational() ? "Cotar frete para " + count + " unidade(s) ↗" : "Consultar " + count + " unidade(s) pelo WhatsApp ↗";
      }
      quantity.removeAttribute("aria-invalid");
      const error = document.getElementById("nfc-quantity-error");
      if (error) error.hidden = true;
    } else {
      total.textContent = "Confira a quantidade";
      if (summary) summary.textContent = "quantidade inválida";
      if (chat) {chat.href = "#nfc-quantity";chat.setAttribute("aria-disabled","true");}
    }
  };
  const updateShipping = () => {
    const nationwide = isNational();
    if (localAddress) {
      localAddress.hidden = nationwide;
      localAddress.querySelectorAll("input[required]").forEach(input => {input.disabled = nationwide;});
    }
    if (localConfirmation) {
      localConfirmation.hidden = nationwide;
      const check = localConfirmation.querySelector("input");
      if (check) check.disabled = nationwide;
    }
    if (submit) {
      submit.hidden = nationwide;
      submit.disabled = nationwide;
    }
    if (quote) {
      quote.hidden = !nationwide;
      if (nationwide) {
        const count = Number(quantity.value);
        const url = new URL("https://wa.me/5591986152222");
        url.searchParams.set("text", "Olá! Gostaria de comprar " + (Number.isSafeInteger(count)?count:1) + " plaquinha(s) NFC da G Tech. CEP: " + (cep?.value || "a informar") + ", cidade: " + (city?.value || "a informar") + ", UF: " + (state?.value || "a informar") + ". Podem informar o frete e o total antes do pagamento?");
        quote.href = url.toString();
      }
    }
    if (checkoutNotice) checkoutNotice.textContent = nationwide ?
      "Fora de Belém: somente cotação de frete. Não será cobrado antes do preço total ser confirmado." :
      "Belém/PA: entrega incluída no valor anunciado; informe o endereço completo.";
    update();
  };
  region?.addEventListener("change", updateShipping);
  [cep,city,state].forEach(input => input?.addEventListener("input",updateShipping));
  quantity.addEventListener("input", update);
  quantity.addEventListener("change", update);
  document.querySelectorAll("[data-quantity-step]").forEach(button => button.addEventListener("click", () => {
    const step = Number(button.dataset.quantityStep);
    const current = Number(quantity.value);
    const next = Math.min(maximum, Math.max(minimum, (Number.isInteger(current) ? current : 1) + step));
    quantity.value = String(next);
    update();
  }));
  form?.addEventListener("submit", () => {
    const submit = form.querySelector("button[type=submit]");
    if (submit && form.checkValidity()) {
      submit.disabled = true;
      submit.textContent = "Preparando pagamento...";
    }
  });
  updateShipping();
})();

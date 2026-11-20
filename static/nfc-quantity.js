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
        link.searchParams.set("text", "Olá! Vim pelo site da G Tech e quero consultar a compra de " + description + ". Valor previsto: " + money.format(count * cents / 100) + ". Entrega em Belém/PA. Podem confirmar estoque e prazo?");
        chat.href = link.toString();
        chat.removeAttribute("aria-disabled");
        chat.textContent = "Consultar " + count + " unidade(s) pelo WhatsApp ↗";
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
  update();
})();

/* G Tech NFC: UI-only amount preview. The server owns stock, price, and quantity. */
(() => {
  "use strict";
  const form = document.getElementById("checkout-form");
  const quantity = document.getElementById("nfc-quantity");
  const total = document.getElementById("nfc-total-price");
  const summary = document.getElementById("nfc-quantity-summary");
  if (!form || !quantity || !total) return;
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
      quantity.removeAttribute("aria-invalid");
      const error = document.getElementById("nfc-quantity-error");
      if (error) error.hidden = true;
    } else {
      total.textContent = "Confira a quantidade";
      if (summary) summary.textContent = "quantidade inválida";
    }
  };
  quantity.addEventListener("input", update);
  quantity.addEventListener("change", update);
  form.querySelectorAll("[data-quantity-step]").forEach(button => button.addEventListener("click", () => {
    const step = Number(button.dataset.quantityStep);
    const current = Number(quantity.value);
    const next = Math.min(maximum, Math.max(minimum, (Number.isInteger(current) ? current : 1) + step));
    quantity.value = String(next);
    update();
  }));
  form.addEventListener("submit", () => {
    const submit = form.querySelector("button[type=submit]");
    if (submit && form.checkValidity()) {
      submit.disabled = true;
      submit.textContent = "Preparando pagamento...";
    }
  });
  update();
})();

/* G Tech: field-level validation, no draft persistence or analytics. */
(() => {
  "use strict";
  const areaCodes = new Set([11,12,13,14,15,16,17,18,19,21,22,24,27,28,31,32,33,34,35,37,38,
    41,42,43,44,45,46,47,48,49,51,53,54,55,61,62,63,64,65,66,67,68,69,71,73,74,75,77,79,
    81,82,83,84,85,86,87,88,89,91,92,93,94,95,96,97,98,99]);
  const validPhone = (raw) => {
    let digits = String(raw || "").replace(/\D/g, "");
    if (digits.startsWith("55") && digits.length === 13) digits = digits.slice(2);
    if (digits.length !== 11 || !areaCodes.has(Number(digits.slice(0, 2))) || digits[2] !== "9") return false;
    const subscriber = digits.slice(2), tail = subscriber.slice(1);
    if (new Set(subscriber).size < 3) return false;
    if (/^(\d)\1{7}$/.test(tail) || ["12345678","87654321"].includes(tail)) return false;
    return true;
  };
  const message = "Informe um celular brasileiro válido com DDD e nono dígito. Não aceitamos números de exemplo.";
  for (const formId of ["quote-form", "checkout-form"]) {
    const form = document.getElementById(formId);
    if (!form) continue;
    const input = form.querySelector('input[name="whatsapp"]');
    const error = document.getElementById(formId === "quote-form" ? "quote-phone-error" : "checkout-phone-error");
    if (!input || !error) continue;
    const mark = (bad) => {
      if (bad) {
        input.setAttribute("aria-invalid", "true");
        error.textContent = message;
        error.hidden = false;
      } else {
        input.removeAttribute("aria-invalid");
        error.textContent = "";
        error.hidden = true;
        input.setCustomValidity("");
      }
    };
    input.addEventListener("blur", () => { if (input.value.trim()) mark(!validPhone(input.value)); });
    input.addEventListener("input", () => { if (input.getAttribute("aria-invalid") === "true") mark(!validPhone(input.value)); });
    form.addEventListener("submit", (event) => {
      if (validPhone(input.value)) { mark(false); return; }
      event.preventDefault();
      event.stopImmediatePropagation();
      mark(true);
      input.focus();
    }, true);
    if (input.getAttribute("aria-invalid") === "true") input.focus({preventScroll:true});
  }
})();

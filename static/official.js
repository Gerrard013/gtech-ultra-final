(() => {
  "use strict";
  const root = document.documentElement;
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const safeScroll = reduced.matches ? "auto" : "smooth";
  const nav = document.getElementById("menu-links");
  const menuButton = document.getElementById("menu-button");
  const closeNav = () => {
    nav?.classList.remove("open");
    menuButton?.setAttribute("aria-expanded", "false");
    menuButton?.setAttribute("aria-label", "Abrir menu");
  };
  menuButton?.addEventListener("click", () => {
    const isOpen = nav?.classList.toggle("open") || false;
    menuButton.setAttribute("aria-expanded", String(isOpen));
    menuButton.setAttribute("aria-label", isOpen ? "Fechar menu" : "Abrir menu");
  });
  nav?.querySelectorAll("a").forEach(link => link.addEventListener("click", closeNav));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeNav();
  });
  document.addEventListener("click", event => {
    if (nav?.classList.contains("open") && !nav.contains(event.target) && !menuButton?.contains(event.target)) closeNav();
  });

  const progress = document.getElementById("scroll-progress");
  let pending = false;
  const updateProgress = () => {
    const remaining = Math.max(0, root.scrollHeight - window.innerHeight);
    if (progress) progress.style.width = ((remaining > 0 ? Math.min(1, window.scrollY / remaining) : 0) * 100).toFixed(1) + "%";
    pending = false;
  };
  const onScroll = () => {
    if (pending) return;
    pending = true;
    window.requestAnimationFrame(updateProgress);
  };
  window.addEventListener("scroll", onScroll, {passive:true});
  window.addEventListener("resize", onScroll, {passive:true});
  updateProgress();

  const observerTargets = document.querySelectorAll(".reveal");
  if (!reduced.matches && "IntersectionObserver" in window) {
    const io = new IntersectionObserver((entries, observer) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    }, {threshold: 0.07, rootMargin:"0px 0px 30px 0px"});
    observerTargets.forEach(el => io.observe(el));
    document.body.classList.add("js-ready");
  } else {
    observerTargets.forEach(el => el.classList.add("visible"));
  }

  const select = document.getElementById("service-select");
  document.querySelectorAll("[data-product]").forEach(link => link.addEventListener("click", () => {
    if (select) select.value = link.getAttribute("data-product") || "";
  }));

  const origin = document.getElementById("origem");
  const params = new URLSearchParams(location.search);
  if (origin) {
    const labels = ["utm_source", "utm_medium", "utm_campaign"]
      .map(k => String(params.get(k) || "").replace(/[^a-z0-9_\- .]/gi, "").slice(0, 38))
      .filter(Boolean);
    origin.value = (labels.length ? "site_oficial_v2|" + labels.join("|") : "site_oficial_v2").slice(0, 180);
  }

  const form = document.getElementById("quote-form");
  const phone = form?.querySelector('input[name="whatsapp"]');
  phone?.addEventListener("input", () => {
    const digits = phone.value.replace(/\D/g, "");
    if (digits.length > 13) phone.value = digits.slice(0, 13);
  });
  form?.addEventListener("submit", event => {
    if (!form.checkValidity()) return;
    const digits = (phone?.value || "").replace(/\D/g, "");
    const normalized = digits.startsWith("55") && digits.length >= 12 ? digits.slice(2) : digits;
    if (!/^\d{10,11}$/.test(normalized)) {
      event.preventDefault();
      phone.setCustomValidity("Digite um número com DDD, por exemplo (91) 99999-9999.");
      phone.reportValidity();
      return;
    }
    const button = form.querySelector(".form-submit");
    if (button) {
      button.disabled = true;
      button.textContent = "Enviando solicitação...";
    }
  });
  phone?.addEventListener("input", () => phone.setCustomValidity(""));

  const video = document.getElementById("showcase-video");
  const toggle = document.getElementById("video-toggle");
  if (video) {
    if (reduced.matches) video.pause();
    toggle?.addEventListener("click", () => {
      if (video.paused) {
        video.play().then(() => {
          toggle.textContent = "Pausar animação";
          toggle.setAttribute("aria-label", "Pausar vídeo");
        }).catch(() => {});
      } else {
        video.pause();
        toggle.textContent = "Reproduzir animação";
        toggle.setAttribute("aria-label", "Reproduzir vídeo");
      }
    });
  }
})();

(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const coarsePointer = window.matchMedia('(pointer: coarse)').matches;

  const cursor = document.querySelector('.cursor-glow');
  if (cursor && !coarsePointer && !reduceMotion) {
    window.addEventListener('pointermove', (event) => {
      cursor.style.left = `${event.clientX}px`;
      cursor.style.top = `${event.clientY}px`;
    }, { passive: true });
  }

  const progressBar = document.querySelector('.scroll-progress span');
  const updateProgress = () => {
    if (!progressBar) return;
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const progress = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
    progressBar.style.width = `${Math.min(100, Math.max(0, progress))}%`;
  };
  window.addEventListener('scroll', updateProgress, { passive: true });
  updateProgress();

  const revealObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        revealObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

  document.querySelectorAll('.reveal').forEach((element, index) => {
    if (reduceMotion) {
      element.classList.add('is-visible');
      return;
    }
    element.style.transitionDelay = `${Math.min(index % 4, 3) * 70}ms`;
    revealObserver.observe(element);
  });

  if (!coarsePointer && !reduceMotion) {
    document.querySelectorAll('[data-tilt]').forEach((element) => {
      const strength = Number(element.dataset.tiltStrength || 5);
      element.addEventListener('pointermove', (event) => {
        const rect = element.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        element.style.transform = `perspective(1200px) rotateX(${-y * strength}deg) rotateY(${x * strength}deg) translateY(-2px)`;
      });
      element.addEventListener('pointerleave', () => {
        element.style.transform = 'perspective(1200px) rotateX(0deg) rotateY(0deg) translateY(0)';
      });
    });

    document.querySelectorAll('.magnetic').forEach((element) => {
      element.addEventListener('pointermove', (event) => {
        const rect = element.getBoundingClientRect();
        const x = event.clientX - rect.left - rect.width / 2;
        const y = event.clientY - rect.top - rect.height / 2;
        element.style.transform = `translate(${x * 0.06}px, ${y * 0.06}px)`;
      });
      element.addEventListener('pointerleave', () => {
        element.style.transform = '';
      });
    });

    const stage = document.querySelector('[data-parallax-stage]');
    if (stage) {
      stage.addEventListener('pointermove', (event) => {
        const rect = stage.getBoundingClientRect();
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        stage.querySelectorAll('[data-float-depth]').forEach((chip) => {
          const depth = Number(chip.dataset.floatDepth || 18);
          chip.style.transform = `translate3d(${x * depth}px, ${y * depth}px, ${depth}px)`;
        });
      });
      stage.addEventListener('pointerleave', () => {
        stage.querySelectorAll('[data-float-depth]').forEach((chip) => {
          chip.style.transform = '';
        });
      });
    }
  }

  const menuToggle = document.querySelector('.menu-toggle');
  const mobileMenu = document.querySelector('#mobile-menu');
  const closeMenu = () => {
    if (!menuToggle || !mobileMenu) return;
    menuToggle.setAttribute('aria-expanded', 'false');
    menuToggle.setAttribute('aria-label', 'Abrir menu');
    mobileMenu.hidden = true;
    document.body.classList.remove('menu-open');
  };

  if (menuToggle && mobileMenu) {
    menuToggle.addEventListener('click', () => {
      const expanded = menuToggle.getAttribute('aria-expanded') === 'true';
      menuToggle.setAttribute('aria-expanded', String(!expanded));
      menuToggle.setAttribute('aria-label', expanded ? 'Abrir menu' : 'Fechar menu');
      mobileMenu.hidden = expanded;
      document.body.classList.toggle('menu-open', !expanded);
    });
    mobileMenu.querySelectorAll('a').forEach((link) => link.addEventListener('click', closeMenu));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeMenu();
    });
  }

  const navLinks = [...document.querySelectorAll('.desktop-nav a')];
  const watchedSections = navLinks
    .map((link) => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
  if (watchedSections.length) {
    const sectionObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        navLinks.forEach((link) => {
          link.classList.toggle('active', link.getAttribute('href') === `#${entry.target.id}`);
        });
      });
    }, { rootMargin: '-35% 0px -55% 0px', threshold: 0 });
    watchedSections.forEach((section) => sectionObserver.observe(section));
  }

  const lightbox = document.querySelector('.lightbox');
  const lightboxImage = lightbox?.querySelector('img');
  const lightboxClose = lightbox?.querySelector('.lightbox-close');
  const closeLightbox = () => {
    if (!lightbox) return;
    lightbox.hidden = true;
    document.body.style.overflow = '';
  };

  document.querySelectorAll('[data-lightbox]').forEach((button) => {
    button.addEventListener('click', () => {
      if (!lightbox || !lightboxImage) return;
      lightboxImage.src = button.dataset.lightbox;
      lightbox.hidden = false;
      document.body.style.overflow = 'hidden';
      lightboxClose?.focus();
    });
  });
  lightboxClose?.addEventListener('click', closeLightbox);
  lightbox?.addEventListener('click', (event) => {
    if (event.target === lightbox) closeLightbox();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && lightbox && !lightbox.hidden) closeLightbox();
  });

  const form = document.querySelector('.multi-form');
  const steps = form ? [...form.querySelectorAll('.form-step')] : [];
  const progressButtons = form ? [...form.querySelectorAll('[data-step-jump]')] : [];
  const progressLines = form ? [...form.querySelectorAll('.form-progress i')] : [];
  let currentStep = 1;

  const showStep = (stepNumber) => {
    if (!form || !steps.length) return;
    currentStep = Math.min(3, Math.max(1, stepNumber));
    steps.forEach((step) => {
      const active = Number(step.dataset.step) === currentStep;
      step.hidden = !active;
      step.classList.toggle('active', active);
    });
    progressButtons.forEach((button, index) => {
      const step = index + 1;
      button.classList.toggle('active', step === currentStep);
      button.classList.toggle('complete', step < currentStep);
      button.setAttribute('aria-current', step === currentStep ? 'step' : 'false');
    });
    progressLines.forEach((line, index) => {
      line.classList.toggle('complete', index + 1 < currentStep);
    });
    form.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'center' });
  };

  const validateField = (field) => {
    const error = field.closest('label')?.querySelector('.field-error');
    let message = '';
    const value = field.value.trim();

    if (field.required && !value) {
      message = 'Preencha este campo para continuar.';
    } else if (field.name === 'whatsapp') {
      const digits = value.replace(/\D/g, '');
      if (digits.length < 10 || digits.length > 13) message = 'Digite um WhatsApp válido com DDD.';
    }

    field.classList.toggle('invalid', Boolean(message));
    field.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (error) error.textContent = message;
    return !message;
  };

  const validateCurrentStep = () => {
    const step = steps.find((item) => Number(item.dataset.step) === currentStep);
    if (!step) return true;
    const fields = [...step.querySelectorAll('input[required], select[required], textarea[required]')];
    const results = fields.map(validateField);
    const firstInvalid = fields.find((field) => field.classList.contains('invalid'));
    firstInvalid?.focus();
    return results.every(Boolean);
  };

  if (form) {
    form.querySelectorAll('input, select, textarea').forEach((field) => {
      field.addEventListener('blur', () => validateField(field));
      field.addEventListener('input', () => {
        if (field.classList.contains('invalid')) validateField(field);
      });
    });

    form.querySelectorAll('.next-step').forEach((button) => {
      button.addEventListener('click', () => {
        if (validateCurrentStep()) showStep(currentStep + 1);
      });
    });
    form.querySelectorAll('.prev-step').forEach((button) => {
      button.addEventListener('click', () => showStep(currentStep - 1));
    });
    progressButtons.forEach((button) => {
      button.addEventListener('click', () => {
        const target = Number(button.dataset.stepJump);
        if (target < currentStep || validateCurrentStep()) showStep(target);
      });
    });

    const whatsappInput = form.querySelector('input[name="whatsapp"]');
    whatsappInput?.addEventListener('input', (event) => {
      const digits = event.target.value.replace(/\D/g, '').slice(0, 11);
      let formatted = digits;
      if (digits.length > 2) formatted = `(${digits.slice(0, 2)}) ${digits.slice(2)}`;
      if (digits.length > 7) formatted = `(${digits.slice(0, 2)}) ${digits.slice(2, 7)}-${digits.slice(7)}`;
      event.target.value = formatted;
    });

    form.addEventListener('submit', (event) => {
      if (!validateCurrentStep()) {
        event.preventDefault();
        return;
      }
      const submitButton = form.querySelector('.submit-button');
      submitButton?.classList.add('loading');
      submitButton?.setAttribute('aria-busy', 'true');
    });
  }

  const serviceSelect = document.querySelector('#service-select');
  document.querySelectorAll('[data-service-choice]').forEach((button) => {
    button.addEventListener('click', () => {
      if (serviceSelect) serviceSelect.value = button.dataset.serviceChoice || '';
      showStep(2);
      document.querySelector('#diagnostico')?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth' });
    });
  });

  const params = new URLSearchParams(window.location.search);
  const originField = document.querySelector('#origem');
  if (originField) {
    const source = params.get('utm_source') || 'site_gtech';
    const medium = params.get('utm_medium') || '';
    const campaign = params.get('utm_campaign') || '';
    originField.value = [source, medium, campaign].filter(Boolean).join('|');
  }
})();

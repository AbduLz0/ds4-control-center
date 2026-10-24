/* DS4 Control Center docs interactions.
   Vanilla JS, no dependencies. Everything degrades to readable content. */
(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');

  /* ---------- scroll progress + sticky header ---------- */
  const header = $('#site-header');
  const progress = $('#scroll-progress');
  let scrollTick = false;

  function onScroll() {
    if (scrollTick) return;
    scrollTick = true;
    requestAnimationFrame(() => {
      const y = window.scrollY || document.documentElement.scrollTop;
      const max = document.documentElement.scrollHeight - window.innerHeight;
      if (progress) progress.style.width = (max > 0 ? Math.min(100, (y / max) * 100) : 0) + '%';
      if (header) header.classList.toggle('is-scrolled', y > 18);
      scrollTick = false;
    });
  }

  window.addEventListener('scroll', onScroll, { passive: true });
  window.addEventListener('resize', onScroll);
  onScroll();

  /* ---------- mobile menu ---------- */
  const menuButton = $('.menu-toggle');
  const nav = $('#site-nav');

  function closeMenu() {
    if (!header || !menuButton) return;
    header.classList.remove('nav-open');
    menuButton.setAttribute('aria-expanded', 'false');
    menuButton.setAttribute('aria-label', 'Open menu');
  }

  if (menuButton && header) {
    menuButton.addEventListener('click', () => {
      const open = header.classList.toggle('nav-open');
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    });

    if (nav) {
      nav.addEventListener('click', (event) => {
        if (event.target.closest('a')) closeMenu();
      });
    }

    document.addEventListener('click', (event) => {
      if (!header.classList.contains('nav-open')) return;
      if (!header.contains(event.target)) closeMenu();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeMenu();
    });
  }

  /* ---------- reveal on scroll ---------- */
  const revealItems = $$('[data-reveal]');
  revealItems.forEach((item, index) => {
    item.style.setProperty('--reveal-delay', `${(index % 4) * 55}ms`);
  });

  if (!reduceMotion.matches && 'IntersectionObserver' in window) {
    const revealObserver = new IntersectionObserver((entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -7% 0px' });
    revealItems.forEach((item) => revealObserver.observe(item));
  } else {
    revealItems.forEach((item) => item.classList.add('is-visible'));
  }

  /* ---------- pointer tilt on the hero frame ---------- */
  const canTilt = window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  if (canTilt && !reduceMotion.matches) {
    $$('[data-tilt]').forEach((frame) => {
      let raf = 0;
      let pointerId = null;

      const reset = () => {
        cancelAnimationFrame(raf);
        pointerId = null;
        frame.style.setProperty('--tilt-x', '0deg');
        frame.style.setProperty('--tilt-y', '0deg');
      };

      frame.addEventListener('pointermove', (event) => {
        if (pointerId !== null && event.pointerId !== pointerId) return;
        pointerId = event.pointerId;
        const rect = frame.getBoundingClientRect();
        const px = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) - 0.5;
        const py = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) - 0.5;
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
          frame.style.setProperty('--tilt-x', `${(-py * 4).toFixed(2)}deg`);
          frame.style.setProperty('--tilt-y', `${(px * 6).toFixed(2)}deg`);
        });
      });

      frame.addEventListener('pointerleave', reset);
      frame.addEventListener('pointercancel', reset);
    });
  }

  /* ---------- screenshot lightbox ---------- */
  const lightbox = $('#lightbox');
  const lightboxImage = $('#lightbox-image');
  const lightboxTitle = $('#lightbox-title');
  const lightboxCaption = $('#lightbox-caption');
  const lightboxCount = $('#lightbox-count');
  const lightboxItems = $$('[data-lightbox]');
  let lightboxIndex = 0;
  let lightboxOpener = null;

  function setLightboxSlide(index) {
    if (!lightboxItems.length) return;
    lightboxIndex = (index + lightboxItems.length) % lightboxItems.length;
    const item = lightboxItems[lightboxIndex];
    const title = item.dataset.title || 'Screenshot';
    if (lightboxImage) {
      lightboxImage.src = item.dataset.full || item.querySelector('img')?.src || '';
      lightboxImage.alt = title;
    }
    if (lightboxTitle) lightboxTitle.textContent = title;
    if (lightboxCaption) lightboxCaption.textContent = item.dataset.caption || '';
    if (lightboxCount) lightboxCount.textContent = `${lightboxIndex + 1} / ${lightboxItems.length}`;
  }

  function openLightbox(index, opener) {
    if (!lightbox || typeof lightbox.showModal !== 'function') {
      const href = lightboxItems[index]?.dataset.full;
      if (href) window.open(href, '_blank', 'noopener');
      return;
    }
    lightboxOpener = opener || null;
    setLightboxSlide(index);
    lightbox.showModal();
    document.body.classList.add('lightbox-open');
    $('[data-lightbox-close]', lightbox)?.focus();
  }

  function closeLightbox() {
    if (!lightbox || !lightbox.open) return;
    lightbox.close();
  }

  if (lightbox) {
    lightboxItems.forEach((item, index) => {
      item.addEventListener('click', (event) => {
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
        event.preventDefault();
        openLightbox(index, item);
      });
    });

    $('[data-lightbox-close]', lightbox)?.addEventListener('click', closeLightbox);
    $('[data-lightbox-prev]', lightbox)?.addEventListener('click', () => setLightboxSlide(lightboxIndex - 1));
    $('[data-lightbox-next]', lightbox)?.addEventListener('click', () => setLightboxSlide(lightboxIndex + 1));

    lightbox.addEventListener('click', (event) => {
      if (event.target === lightbox) closeLightbox();
    });

    lightbox.addEventListener('close', () => {
      document.body.classList.remove('lightbox-open');
      lightboxOpener?.focus?.();
      lightboxOpener = null;
    });

    document.addEventListener('keydown', (event) => {
      if (!lightbox.open) return;
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        setLightboxSlide(lightboxIndex - 1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        setLightboxSlide(lightboxIndex + 1);
      }
    });
  }

  /* ---------- copy buttons ---------- */
  async function copyText(text) {
    if (!text) return false;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (error) {
      /* fall through to the textarea fallback */
    }
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.setAttribute('readonly', '');
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      textarea.style.pointerEvents = 'none';
      document.body.appendChild(textarea);
      textarea.select();
      const copied = document.execCommand('copy');
      textarea.remove();
      return copied;
    } catch (error) {
      return false;
    }
  }

  $$('[data-copy], [data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
      const target = button.dataset.copyTarget;
      const text = button.dataset.copy || (target ? document.getElementById(target)?.textContent : '') || '';
      const label = button.querySelector('span');
      const previous = label ? label.textContent : '';
      const ok = await copyText(text.trim());
      if (!ok) return;
      button.classList.add('is-copied');
      if (label) label.textContent = 'Copied';
      window.setTimeout(() => {
        button.classList.remove('is-copied');
        if (label) label.textContent = previous;
      }, 1600);
    });
  });

  /* ---------- active section in nav ---------- */
  const navSectionIds = ['features', 'gallery', 'install', 'faq'];
  const navLinks = new Map();
  $$('.site-nav a[href^="#"]').forEach((link) => {
    const id = link.getAttribute('href').slice(1);
    if (navSectionIds.includes(id)) navLinks.set(id, link);
  });

  function updateActiveNav() {
    if (!navLinks.size) return;
    const marker = window.scrollY + window.innerHeight * 0.34;
    let active = '';
    navSectionIds.forEach((id) => {
      const section = document.getElementById(id);
      if (!section) return;
      const top = section.getBoundingClientRect().top + window.scrollY;
      if (top <= marker) active = id;
    });
    navLinks.forEach((link, id) => link.classList.toggle('is-active', id === active));
  }

  window.addEventListener('scroll', updateActiveNav, { passive: true });
  window.addEventListener('resize', updateActiveNav);
  updateActiveNav();

  /* ---------- misc ---------- */
  const year = $('#year');
  if (year) year.textContent = String(new Date().getFullYear());

  document.body.classList.add('loaded');
  window.__ds4DocsReady = true;
})();

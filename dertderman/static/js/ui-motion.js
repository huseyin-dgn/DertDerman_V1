(() => {
  "use strict";
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const regions = [...document.querySelectorAll('[data-motion-region]')];
  const onscreen = new Set();
  let paused = false;
  const syncMotion = () => {
    regions.forEach((region) => {
      const running = onscreen.has(region) && !document.hidden && !reducedMotion.matches && !paused;
      region.classList.toggle('motion-running', running);
      if (running) region.classList.add('motion-seen');
    });
    document.dispatchEvent(new Event('dd-motion-change'));
  };
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(({target, isIntersecting}) => { if (isIntersecting) onscreen.add(target); else onscreen.delete(target); });
      syncMotion();
    });
    regions.forEach((region) => observer.observe(region));
  }
  reducedMotion.addEventListener('change', syncMotion);
  document.addEventListener('visibilitychange', syncMotion);
  document.querySelectorAll('[data-motion-toggle]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', () => {
      paused = !paused;
      button.setAttribute('aria-pressed', String(paused));
      button.textContent = paused ? 'Hareketi sürdür' : 'Hareketi durdur';
      syncMotion();
    });
  });
  const metrics = document.querySelector('[data-count-region]');
  if (metrics && 'IntersectionObserver' in window) {
    let countFrame = 0;
    let counted = false;
    const values = [...metrics.querySelectorAll('[data-count]')].map((element) => ({element, value: Number(element.dataset.count)}));
    const finish = () => { cancelAnimationFrame(countFrame); countFrame = 0; metrics.classList.remove('is-counting'); observer.disconnect(); };
    const observer = new IntersectionObserver((entries) => {
      const visible = entries[0].isIntersecting;
      if (!visible) { if (counted) finish(); return; }
      if (counted) return;
      counted = true;
      if (reducedMotion.matches || document.hidden || values.some(({value}) => !Number.isSafeInteger(value) || value < 0)) { finish(); return; }
      const formatter = new Intl.NumberFormat('tr-TR');
      const start = performance.now();
      metrics.classList.add('is-counting');
      const draw = (now) => {
        const progress = Math.min((now - start) / 700, 1);
        values.forEach(({element, value}) => { element.textContent = formatter.format(Math.round(value * (1 - (1 - progress) ** 3))); });
        if (progress < 1) countFrame = requestAnimationFrame(draw); else finish();
      };
      draw(start);
    });
    observer.observe(metrics);
    document.addEventListener('visibilitychange', () => { if (document.hidden) finish(); });
    reducedMotion.addEventListener('change', finish);
  }
  document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    const input = document.getElementById(button.getAttribute('aria-controls'));
    if (!input || input.type !== 'password') return;
    button.hidden = false;
    button.parentElement.classList.add('password-enhanced');
    button.addEventListener('click', () => {
      const visible = input.type === 'password';
      input.type = visible ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(visible));
      button.textContent = visible ? 'Gizle' : 'Göster';
      button.setAttribute('aria-label', `${input.labels[0].textContent.trim()}: ${button.textContent}`);
    });
  });
  const visual = document.querySelector('.auth-page .auth-story .solution-visual');
  if (visual) {
    const enabled = window.matchMedia('(min-width: 768px) and (pointer: fine) and (hover: hover) and (prefers-reduced-motion: no-preference)');
    const layers = [...visual.querySelectorAll('[data-visual-depth]')].map((element) => ({element, depth: Number(element.dataset.visualDepth)}));
    let bounds, frame = 0, previous = 0, x = 0, y = 0, targetX = 0, targetY = 0;
    const draw = (time) => {
      const blend = 1 - Math.exp(-Math.min(time - (previous || time - 16), 50) / 85);
      previous = time;
      x += (targetX - x) * blend;
      y += (targetY - y) * blend;
      const settled = Math.abs(targetX - x) + Math.abs(targetY - y) < 0.02;
      if (settled) { x = targetX; y = targetY; }
      layers.forEach(({element, depth}) => {
        element.style.transform = x || y ? `translate(${x * depth}px, ${y * depth}px)` : '';
      });
      frame = settled ? 0 : requestAnimationFrame(draw);
      if (settled) previous = 0;
    };
    const animate = () => { if (!frame) frame = requestAnimationFrame(draw); };
    const reset = () => {
      cancelAnimationFrame(frame);
      bounds = undefined;
      frame = previous = x = y = targetX = targetY = 0;
      layers.forEach(({element}) => { element.style.transform = ''; });
    };
    visual.addEventListener('pointerenter', (event) => {
      if (enabled.matches && visual.classList.contains('motion-running') && event.pointerType === 'mouse') bounds = visual.getBoundingClientRect();
    });
    visual.addEventListener('pointermove', (event) => {
      if (!bounds || !enabled.matches || !visual.classList.contains('motion-running') || event.pointerType !== 'mouse') return;
      const clamp = (value) => Math.max(-1, Math.min(1, value));
      targetX = clamp((event.clientX - bounds.left) / bounds.width * 2 - 1) * 8;
      targetY = clamp((event.clientY - bounds.top) / bounds.height * 2 - 1) * 8;
      animate();
    });
    const leave = () => { bounds = undefined; targetX = targetY = 0; if (enabled.matches) animate(); };
    visual.addEventListener('pointerleave', leave);
    visual.addEventListener('pointercancel', leave);
    enabled.addEventListener('change', reset);
    window.addEventListener('resize', reset);
    document.addEventListener('visibilitychange', () => { if (document.hidden) reset(); });
    document.addEventListener('dd-motion-change', () => { if (!visual.classList.contains('motion-running')) reset(); });
  }
  // Storage controls a decorative homepage introduction only.
  const intro = document.querySelector("[data-brand-intro]");
  if (intro) {
    try {
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (!reduced && !window.sessionStorage.getItem("dd-brand-intro-seen")) {
        intro.classList.add("intro-play");
        window.sessionStorage.setItem("dd-brand-intro-seen", "1");
      }
    } catch (_) { /* Storage may be unavailable; the complete page stays visible. */ }
  }
  const toggle = document.querySelector("[data-nav-toggle]");
  const links = document.getElementById("site-links");
  if (toggle && links && window.matchMedia) {
    const narrow = window.matchMedia("(max-width: 1100px)");
    const setOpen = (open) => {
      links.dataset.collapsed = String(!open);
      toggle.setAttribute("aria-expanded", String(open));
    };
    const sync = () => { toggle.hidden = !narrow.matches; setOpen(!narrow.matches); };
    toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && narrow.matches && toggle.getAttribute("aria-expanded") === "true") {
        setOpen(false); toggle.focus();
      }
    });
    if (narrow.addEventListener) narrow.addEventListener("change", sync);
    sync();
  }
  document.querySelectorAll('[data-feedback]').forEach((banner) => {
    const close = banner.querySelector('.feedback-close');
    if (!close) return;
    close.hidden = false;
    let timer;
    const dismiss = () => { clearTimeout(timer); banner.hidden = true; };
    const stop = () => clearTimeout(timer);
    const schedule = () => {
      stop();
      if (['success', 'info'].includes(banner.dataset.feedback)) timer = setTimeout(dismiss, 6000);
    };
    close.addEventListener('click', dismiss);
    banner.addEventListener('mouseenter', stop);
    banner.addEventListener('mouseleave', () => { if (!banner.contains(document.activeElement)) schedule(); });
    banner.addEventListener('focusin', stop);
    banner.addEventListener('focusout', () => { if (!banner.contains(document.activeElement)) schedule(); });
    schedule();
  });
})();

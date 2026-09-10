(() => {
  const root = document.documentElement;
  const buttons = document.querySelectorAll('[data-theme-toggle]');
  const update = () => {
    const dark = root.dataset.theme === 'dark';
    buttons.forEach((button) => {
      button.setAttribute('aria-label', dark ? 'Açık temaya geç' : 'Koyu temaya geç');
      button.setAttribute('aria-pressed', dark ? 'true' : 'false');
    });
  };
  buttons.forEach((button) => button.addEventListener('click', () => {
    const theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    root.dataset.theme = theme;
    try { localStorage.setItem('dd-theme', theme); } catch (_) {}
    update();
  }));
  update();
})();

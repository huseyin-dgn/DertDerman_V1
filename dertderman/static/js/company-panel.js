(() => {
  const shell = document.querySelector('.cp-shell');
  const button = document.querySelector('.cp-menu-button');
  if (!shell || !button) return;
  const setExpanded = (expanded) => {
    shell.dataset.navCollapsed = String(!expanded);
    button.setAttribute('aria-expanded', String(expanded));
  };
  button.hidden = false;
  setExpanded(!window.matchMedia('(max-width: 700px)').matches);
  button.addEventListener('click', () => setExpanded(button.getAttribute('aria-expanded') !== 'true'));
  shell.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && window.matchMedia('(max-width: 700px)').matches) {
      setExpanded(false);
      button.focus();
    }
  });
})();

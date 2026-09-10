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

document.querySelectorAll('[data-logo-uploader]').forEach((uploader) => {
  const input = uploader.querySelector('input[type="file"]');
  const name = uploader.querySelector('[data-logo-name]');
  const action = uploader.querySelector('[data-logo-action]');
  const trigger = uploader.querySelector('[data-logo-trigger]');
  const preview = uploader.querySelector('.cp-logo-upload-preview');
  if (!input || !name || !preview) return;
  if (trigger) trigger.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    const file = input.files?.[0];
    if (!file) return;
    name.textContent = file.name;
    if (action) action.textContent = 'Görseli Değiştir';
    const prior = preview.querySelector('img');
    const image = prior || document.createElement('img');
    image.className = 'cp-logo-upload-image';
    image.alt = 'Seçilen şirket logosu önizlemesi';
    image.src = URL.createObjectURL(file);
    if (!prior) preview.replaceChildren(image);
  });
});

(() => {
  const shell = document.querySelector('.cp-shell');
  const button = document.querySelector('.cp-menu-button');
  const navigation = document.querySelector('#company-navigation');
  const backdrop = document.querySelector('.cp-nav-backdrop');
  const mobile = window.matchMedia('(max-width: 700px)');
  if (!shell || !button || !navigation || !backdrop) return;

  const setExpanded = (expanded) => {
    const open = mobile.matches && expanded;
    shell.dataset.navOpen = String(open);
    button.setAttribute('aria-expanded', String(open));
    backdrop.hidden = !open;
    navigation.inert = mobile.matches && !open;
    document.body.classList.toggle('cp-nav-open', open);
  };

  button.hidden = false;
  setExpanded(false);
  button.addEventListener('click', () => setExpanded(button.getAttribute('aria-expanded') !== 'true'));
  backdrop.addEventListener('click', () => {
    setExpanded(false);
    button.focus();
  });
  navigation.querySelectorAll('a').forEach((link) => {
    link.addEventListener('click', () => setExpanded(false));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && button.getAttribute('aria-expanded') === 'true') {
      setExpanded(false);
      button.focus();
    }
  });
  mobile.addEventListener('change', () => setExpanded(false));
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
    document.querySelectorAll('input[name="selected_avatar"]').forEach((option) => {
      option.checked = false;
    });
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

document.querySelectorAll('input[name="selected_avatar"]').forEach((option) => {
  option.addEventListener('change', () => {
    if (!option.checked) return;
    const uploader = document.querySelector('[data-logo-uploader]');
    const input = uploader?.querySelector('input[type="file"]');
    const name = uploader?.querySelector('[data-logo-name]');
    const preview = uploader?.querySelector('.cp-logo-upload-preview');
    if (input) input.value = '';
    if (name) name.textContent = 'Kurumsal simge seçildi';
    if (preview) {
      const selectedImage = option.closest('.company-avatar-option')
        ?.querySelector('.company-avatar-choice img');
      if (selectedImage) {
        const image = selectedImage.cloneNode();
        image.className = 'cp-logo-upload-image';
        image.alt = 'Seçilen kurumsal simge önizlemesi';
        preview.replaceChildren(image);
      } else {
        const fallback = document.createElement('span');
        fallback.className = 'cp-logo-upload-fallback';
        fallback.textContent = uploader.dataset.companyInitial || '';
        preview.replaceChildren(fallback);
      }
    }
  });
});

(() => {
  const root = document.documentElement;
  const storageKey = 'dd-authenticated-role';
  const currentRole = root.dataset.authRole;
  if (currentRole) sessionStorage.setItem(storageKey, currentRole);

  const navigation = performance.getEntriesByType('navigation')[0];
  let invalidating = false;

  const loginUrlFor = (role) => ({
    USER: '/hesap/giris/',
    COMPANY: '/kurumsal/giris/',
    ADMIN: '/yonetim/giris/',
  })[role] || '/hesap/giris/';

  const csrfToken = () => {
    const item = document.cookie.split(';').map((cookie) => cookie.trim())
      .find((cookie) => cookie.startsWith('csrftoken='));
    return item ? decodeURIComponent(item.slice('csrftoken='.length)) : '';
  };

  const invalidate = () => {
    const role = sessionStorage.getItem(storageKey);
    if (!role || invalidating) return;
    invalidating = true;
    root.style.visibility = 'hidden';
    fetch(root.dataset.historyInvalidateUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-CSRFToken': csrfToken() },
      keepalive: true,
    }).then((response) => {
      if (!response.ok && response.status !== 401) throw new Error('Session invalidation failed');
      sessionStorage.removeItem(storageKey);
      window.location.replace(loginUrlFor(role));
    }).catch(() => {
      invalidating = false;
      root.style.removeProperty('visibility');
    });
  };

  if (navigation?.type === 'back_forward') invalidate();
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) invalidate();
  });
})();

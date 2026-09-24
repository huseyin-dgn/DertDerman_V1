(() => {
  window.addEventListener('pageshow', (event) => {
    // BFCache eski özel DOM'u geri getirirse sayfayı sunucudan tekrar
    // doğrula. Normal geri/ileri gezinmesi aktif oturumu sonlandırmamalıdır.
    if (event.persisted) window.location.reload();
  });
})();

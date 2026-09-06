// Hide the stored document before a back/forward cache snapshot is taken.
window.addEventListener("pagehide", () => {
    document.documentElement.hidden = true;
});

// A restored private page must pass server-side session/role checks again.
window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
        document.documentElement.hidden = true;
        window.location.reload();
    }
});

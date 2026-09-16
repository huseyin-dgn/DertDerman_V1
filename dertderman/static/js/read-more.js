(() => {
    "use strict";

    const DIALOG_ID = "dd-read-more-dialog";
    const RESIZE_DELAY = 120;
    const HEIGHT_TOLERANCE = 3;

    let resizeTimer = null;

    const createDialog = () => {
        let dialog = document.getElementById(DIALOG_ID);

        if (dialog) {
            return dialog;
        }

        dialog = document.createElement("dialog");
        dialog.id = DIALOG_ID;
        dialog.className = "rm-dialog";

        dialog.innerHTML = `
            <div class="rm-dialog__card">
                <header class="rm-dialog__header">
                    <div>
                        <p>DERTDERMAN</p>

                        <h2
                            id="dd-read-more-title"
                            data-rm-title
                        >
                            Metnin tamamı
                        </h2>
                    </div>

                    <button
                        type="button"
                        class="rm-dialog__close"
                        data-rm-close
                        aria-label="Pencereyi kapat"
                    >
                        ×
                    </button>
                </header>

                <div
                    class="rm-dialog__body"
                    data-rm-body
                ></div>

                <footer class="rm-dialog__footer">
                    <button
                        type="button"
                        class="rm-dialog__done"
                        data-rm-close
                    >
                        Kapat
                    </button>
                </footer>
            </div>
        `;

        document.body.appendChild(dialog);

        return dialog;
    };


    const dialog = createDialog();

    const title = dialog.querySelector(
        "[data-rm-title]"
    );

    const body = dialog.querySelector(
        "[data-rm-body]"
    );


    /*
     * Metnin gerçekten clamp sınırını aşıp
     * aşmadığını ölçer.
     *
     * Önce mevcut, kırpılmış yüksekliği alır.
     * Daha sonra aynı elementi çok kısa süreliğine
     * clamp olmadan ölçer ve eski stilini geri koyar.
     *
     * Böylece kısa metinlerde oluşan yanlış
     * "Devamını Oku" butonu engellenir.
     */
    const isOverflowing = (element) => {
        if (!element) {
            return false;
        }

        const initialRect =
            element.getBoundingClientRect();

        /*
         * Element henüz layout içinde değilse
         * yanlış pozitif üretme.
         */
        if (
            initialRect.width <= 0 ||
            initialRect.height <= 0
        ) {
            return false;
        }

        const collapsedHeight =
            initialRect.height;

        /*
         * Elementin mevcut inline style bilgisini
         * eksiksiz sakla.
         */
        const originalStyle =
            element.getAttribute("style");

        /*
         * Clamp'i geçici olarak kaldır.
         */
        element.style.setProperty(
            "-webkit-line-clamp",
            "unset"
        );

        element.style.setProperty(
            "-webkit-box-orient",
            "initial"
        );

        element.style.setProperty(
            "display",
            "block"
        );

        element.style.setProperty(
            "overflow",
            "visible"
        );

        element.style.setProperty(
            "max-height",
            "none"
        );

        element.style.setProperty(
            "height",
            "auto"
        );

        const expandedHeight =
            element
                .getBoundingClientRect()
                .height;

        /*
         * Elementi tam olarak eski durumuna getir.
         */
        if (originalStyle === null) {
            element.removeAttribute(
                "style"
            );
        } else {
            element.setAttribute(
                "style",
                originalStyle
            );
        }

        return (
            expandedHeight >
            collapsedHeight +
                HEIGHT_TOLERANCE
        );
    };


    const refreshButtons = () => {
        const buttons =
            document.querySelectorAll(
                "[data-read-more-target]"
            );

        buttons.forEach((button) => {
            const targetId =
                button.dataset
                    .readMoreTarget;

            if (!targetId) {
                button.style.display =
                    "none";

                return;
            }

            const source =
                document.getElementById(
                    targetId
                );

            if (!source) {
                button.style.display =
                    "none";

                return;
            }

            const shouldShow =
                isOverflowing(source);

            if (shouldShow) {
                button.style.removeProperty(
                    "display"
                );
            } else {
                button.style.display =
                    "none";
            }
        });
    };


    const openDialog = (trigger) => {
        const targetId =
            trigger.dataset
                .readMoreTarget;

        if (!targetId) {
            return;
        }

        const source =
            document.getElementById(
                targetId
            );

        if (!source) {
            return;
        }

        title.textContent =
            trigger.dataset
                .readMoreTitle ||
            "Metnin tamamı";

        /*
         * Kaynak zaten Django tarafından
         * render edilmiş güvenli HTML'dir.
         * linebreaksbr çıktısını da korur.
         */
        body.innerHTML =
            source.innerHTML;

        if (
            typeof dialog.showModal
            === "function"
        ) {
            if (!dialog.open) {
                dialog.showModal();
            }

            return;
        }

        dialog.setAttribute(
            "open",
            ""
        );
    };


    const closeDialog = () => {
        if (
            typeof dialog.close
            === "function"
        ) {
            if (dialog.open) {
                dialog.close();
            }

            return;
        }

        dialog.removeAttribute(
            "open"
        );
    };


    document.addEventListener(
        "click",
        (event) => {
            const trigger =
                event.target.closest(
                    "[data-read-more-target]"
                );

            if (trigger) {
                event.preventDefault();

                openDialog(trigger);

                return;
            }

            const closeButton =
                event.target.closest(
                    "[data-rm-close]"
                );

            if (closeButton) {
                event.preventDefault();

                closeDialog();
            }
        }
    );


    dialog.addEventListener(
        "click",
        (event) => {
            if (
                event.target === dialog
            ) {
                closeDialog();
            }
        }
    );


    window.addEventListener(
        "resize",
        () => {
            window.clearTimeout(
                resizeTimer
            );

            resizeTimer =
                window.setTimeout(
                    refreshButtons,
                    RESIZE_DELAY
                );
        }
    );


    /*
     * Fontlar sonradan yüklenirse metnin satır
     * kırılımları değişebileceği için yeniden ölç.
     */
    const refreshAfterFonts = () => {
        if (
            document.fonts &&
            document.fonts.ready
        ) {
            document.fonts.ready
                .then(() => {
                    refreshButtons();
                })
                .catch(() => {
                    /*
                     * Font ölçümü başarısız olsa bile
                     * sayfanın çalışmasını bozma.
                     */
                });
        }
    };


    const initialize = () => {
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                refreshButtons();
                refreshAfterFonts();
            });
        });
    };


    if (
        document.readyState ===
        "loading"
    ) {
        document.addEventListener(
            "DOMContentLoaded",
            initialize,
            {
                once: true,
            }
        );
    } else {
        initialize();
    }


    window.addEventListener(
        "load",
        refreshButtons,
        {
            once: true,
        }
    );
})();
"use strict";

document.addEventListener("DOMContentLoaded", () => {
    const root = document.querySelector("[data-category-select]");

    if (!root) {
        return;
    }

    const form = root.closest("[data-complaint-filter-form]");
    const trigger = root.querySelector("[data-category-trigger]");
    const menu = root.querySelector("[data-category-menu]");
    const hiddenInput = root.querySelector("[data-category-value]");
    const label = root.querySelector("[data-category-label]");
    const searchInput = root.querySelector("[data-category-search]");
    const options = Array.from(
        root.querySelectorAll("[data-category-option]")
    );
    const emptyState = root.querySelector("[data-category-empty]");

    if (
        !form ||
        !trigger ||
        !menu ||
        !hiddenInput ||
        !label
    ) {
        return;
    }

    const openMenu = () => {
        menu.hidden = false;

        trigger.setAttribute(
            "aria-expanded",
            "true"
        );

        root.classList.add("is-open");

        window.requestAnimationFrame(() => {
            if (searchInput) {
                searchInput.focus();
            }
        });
    };

    const closeMenu = ({
        returnFocus = false
    } = {}) => {
        menu.hidden = true;

        trigger.setAttribute(
            "aria-expanded",
            "false"
        );

        root.classList.remove("is-open");

        if (searchInput) {
            searchInput.value = "";
        }

        options.forEach((option) => {
            option.hidden = false;
        });

        if (emptyState) {
            emptyState.hidden = true;
        }

        if (returnFocus) {
            trigger.focus();
        }
    };

    const toggleMenu = () => {
        if (menu.hidden) {
            openMenu();
        } else {
            closeMenu({
                returnFocus: true
            });
        }
    };

    const selectOption = (option) => {
        const value = option.dataset.value || "";
        const optionLabel =
            option.dataset.label ||
            "Tüm kategoriler";

        hiddenInput.value = value;
        label.textContent = optionLabel;

        options.forEach((item) => {
            const selected = (
                item === option
            );

            item.classList.toggle(
                "is-selected",
                selected
            );

            item.setAttribute(
                "aria-selected",
                selected ? "true" : "false"
            );
        });

        closeMenu();

        form.requestSubmit();
    };

    trigger.addEventListener(
        "click",
        toggleMenu
    );

    options.forEach((option) => {
        option.addEventListener(
            "click",
            () => {
                selectOption(option);
            }
        );
    });

    if (searchInput) {
        searchInput.addEventListener(
            "input",
            () => {
                const query = (
                    searchInput.value
                    .trim()
                    .toLocaleLowerCase("tr-TR")
                );

                let visibleCount = 0;

                options.forEach((option) => {
                    const optionLabel = (
                        option.dataset.label || ""
                    ).toLocaleLowerCase("tr-TR");

                    const visible = (
                        !query ||
                        optionLabel.includes(query)
                    );

                    option.hidden = !visible;

                    if (visible) {
                        visibleCount += 1;
                    }
                });

                if (emptyState) {
                    emptyState.hidden = (
                        visibleCount !== 0
                    );
                }
            }
        );

        searchInput.addEventListener(
            "keydown",
            (event) => {
                if (
                    event.key !== "ArrowDown"
                ) {
                    return;
                }

                const firstVisible = (
                    options.find(
                        (option) =>
                            !option.hidden
                    )
                );

                if (firstVisible) {
                    event.preventDefault();
                    firstVisible.focus();
                }
            }
        );
    }

    options.forEach(
        (option, index) => {
            option.addEventListener(
                "keydown",
                (event) => {
                    if (
                        event.key !== "ArrowDown" &&
                        event.key !== "ArrowUp"
                    ) {
                        return;
                    }

                    event.preventDefault();

                    const visibleOptions = (
                        options.filter(
                            (item) =>
                                !item.hidden
                        )
                    );

                    const currentIndex = (
                        visibleOptions.indexOf(
                            option
                        )
                    );

                    if (
                        currentIndex === -1
                    ) {
                        return;
                    }

                    const direction = (
                        event.key === "ArrowDown"
                            ? 1
                            : -1
                    );

                    let nextIndex = (
                        currentIndex +
                        direction
                    );

                    if (
                        nextIndex <
                        0
                    ) {
                        nextIndex = (
                            visibleOptions.length -
                            1
                        );
                    }

                    if (
                        nextIndex >=
                        visibleOptions.length
                    ) {
                        nextIndex = 0;
                    }

                    visibleOptions[
                        nextIndex
                    ]?.focus();
                }
            );
        }
    );

    document.addEventListener(
        "keydown",
        (event) => {
            if (
                event.key === "Escape" &&
                !menu.hidden
            ) {
                closeMenu({
                    returnFocus: true
                });
            }
        }
    );

    document.addEventListener(
        "click",
        (event) => {
            if (
                menu.hidden ||
                root.contains(event.target)
            ) {
                return;
            }

            closeMenu();
        }
    );
});
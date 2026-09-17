(() => {
  "use strict";

  const root = document.querySelector("[data-assistant-root]");
  if (!root) return;

  const endpoint = root.dataset.endpoint;
  const panel = root.querySelector("[data-assistant-panel]");
  const toggle = root.querySelector("[data-assistant-toggle]");
  const closeButton = root.querySelector("[data-assistant-close]");
  const transcript = root.querySelector("[data-assistant-transcript]");
  const actions = root.querySelector("[data-assistant-actions]");
  const status = root.querySelector("[data-assistant-status]");
  const csrfInput = root.querySelector("input[name='csrfmiddlewaretoken']");

  if (
    !endpoint ||
    !panel ||
    !toggle ||
    !closeButton ||
    !transcript ||
    !actions ||
    !status ||
    !csrfInput
  ) {
    return;
  }

  const MIN_THINKING_MS = 1500;
  const REQUEST_TIMEOUT_MS = 12000;

  let requestInFlight = false;
  let typingIndicator = null;

  const actionButtons = () => [
    ...actions.querySelectorAll("[data-assistant-action]"),
  ];

  const wait = (ms) => (
    new Promise((resolve) => {
      window.setTimeout(resolve, ms);
    })
  );

  const scrollTranscript = () => {
    transcript.scrollTop = transcript.scrollHeight;
  };

  const setOpen = (open) => {
    panel.hidden = !open;

    toggle.setAttribute(
      "aria-expanded",
      open ? "true" : "false"
    );

    toggle.setAttribute(
      "aria-label",
      open
        ? "DertDerman Asistanı kapat"
        : "DertDerman Asistanı aç"
    );

    if (open) {
      window.setTimeout(() => {
        const firstAction = actions.querySelector(
          "[data-assistant-action]:not(:disabled)"
        );

        (firstAction || closeButton).focus();
        scrollTranscript();
      }, 0);

      return;
    }

    toggle.focus();
  };

  const setBusy = (busy) => {
    requestInFlight = busy;

    actions.setAttribute(
      "aria-busy",
      busy ? "true" : "false"
    );

    actionButtons().forEach((button) => {
      button.disabled = busy;
    });

    status.textContent = (
      busy
        ? "Yanıt hazırlanıyor…"
        : ""
    );
  };

  const avatarNode = () => {
    const avatar = document.createElement("span");

    avatar.className = "dd-assistant__avatar";
    avatar.setAttribute(
      "aria-hidden",
      "true"
    );

    avatar.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none">
        <path d="M5.5 9.75A6.5 6.5 0 0 1 12 3.25a6.5 6.5 0 0 1 6.5 6.5v1.5a6.5 6.5 0 0 1-6.5 6.5H9.7l-3.2 2.8v-4.1A6.47 6.47 0 0 1 5.5 13v-3.25Z" fill="currentColor" opacity=".14"/>
        <path d="M9 10.5h.01M12 10.5h.01M15 10.5h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
      </svg>
    `;

    return avatar;
  };

  const makeBubble = (
    text,
    variant
  ) => {
    const row = document.createElement("div");

    row.className = (
      `dd-assistant__message dd-assistant__message--${variant}`
    );

    if (variant === "assistant") {
      row.appendChild(
        avatarNode()
      );
    }

    const bubble = document.createElement("div");

    bubble.className = (
      `dd-assistant__bubble dd-assistant__bubble--${variant}`
    );

    const paragraph = document.createElement("p");
    paragraph.textContent = text;

    bubble.appendChild(
      paragraph
    );

    row.appendChild(
      bubble
    );

    return row;
  };

  const appendUserMessage = (text) => {
    transcript.appendChild(
      makeBubble(
        text,
        "user"
      )
    );

    scrollTranscript();
  };

  const appendError = (text) => {
    const row = makeBubble(
      text,
      "assistant"
    );

    const bubble = row.querySelector(
      ".dd-assistant__bubble"
    );

    if (bubble) {
      bubble.classList.add(
        "dd-assistant__bubble--error"
      );
    }

    transcript.appendChild(
      row
    );

    scrollTranscript();
  };

  const removeTyping = () => {
    if (
      typingIndicator
      && typingIndicator.parentNode
    ) {
      typingIndicator.parentNode.removeChild(
        typingIndicator
      );
    }

    typingIndicator = null;
  };

  const showTyping = () => {
    removeTyping();

    const row = document.createElement("div");

    row.className = (
      "dd-assistant__message "
      + "dd-assistant__message--assistant"
    );

    const typing = document.createElement("div");

    typing.className = "dd-assistant__typing";
    typing.innerHTML = `
      <span class="dd-assistant__typing-dots" aria-hidden="true">
        <span></span><span></span><span></span>
      </span>
      <span>Düşünüyor…</span>
    `;

    row.append(
      avatarNode(),
      typing
    );

    transcript.appendChild(
      row
    );

    typingIndicator = row;

    scrollTranscript();
  };

  const safeSameOriginPath = (rawUrl) => {
    if (
      typeof rawUrl !== "string"
      || !rawUrl.trim()
    ) {
      return null;
    }

    try {
      const parsed = new URL(
        rawUrl,
        window.location.origin
      );

      if (
        parsed.origin
        !== window.location.origin
      ) {
        return null;
      }

      return (
        `${parsed.pathname}`
        + `${parsed.search}`
        + `${parsed.hash}`
      );

    } catch (_error) {
      return null;
    }
  };

  const asNonNegativeInteger = (value) => {
    if (
      !Number.isInteger(value)
      || value < 0
    ) {
      return null;
    }

    return value;
  };

  const renderAccountSummary = (data) => {
    if (
      !data
      || typeof data !== "object"
    ) {
      return null;
    }

    const complaints = data.complaints;
    const notifications = data.notifications;

    if (
      !complaints
      || typeof complaints !== "object"
      || !notifications
      || typeof notifications !== "object"
    ) {
      return null;
    }

    const total = asNonNegativeInteger(
      complaints.total
    );

    const unread = asNonNegativeInteger(
      notifications.unread_count
    );

    if (
      total === null
      || unread === null
    ) {
      return null;
    }

    const card = document.createElement("div");
    card.className = "dd-assistant__summary";

    const metrics = document.createElement("div");
    metrics.className = "dd-assistant__summary-grid";

    [
      ["Şikayet", total],
      ["Okunmamış", unread],
    ].forEach(([label, value]) => {
      const metric = document.createElement("div");
      metric.className = "dd-assistant__summary-metric";

      const labelNode = document.createElement("span");
      labelNode.textContent = label;

      const valueNode = document.createElement("strong");
      valueNode.textContent = String(value);

      metric.append(
        labelNode,
        valueNode
      );

      metrics.appendChild(
        metric
      );
    });

    card.appendChild(
      metrics
    );

    if (
      Array.isArray(
        complaints.status_distribution
      )
    ) {
      const list = document.createElement("ul");
      list.className = "dd-assistant__summary-list";

      complaints.status_distribution.forEach((item) => {
        if (
          !item
          || typeof item !== "object"
          || typeof item.label !== "string"
        ) {
          return;
        }

        const count = asNonNegativeInteger(
          item.count
        );

        if (count === null) {
          return;
        }

        const row = document.createElement("li");
        row.className = "dd-assistant__summary-row";

        const label = document.createElement("span");
        label.textContent = item.label;

        const value = document.createElement("strong");
        value.textContent = String(count);

        row.append(
          label,
          value
        );

        list.appendChild(
          row
        );
      });

      if (list.childElementCount) {
        card.appendChild(
          list
        );
      }
    }

    return card;
  };

  const renderComplaintSummary = (data) => {
    if (
      !data
      || typeof data !== "object"
    ) {
      return null;
    }

    const total = asNonNegativeInteger(
      data.total
    );

    if (total === null) {
      return null;
    }

    const card = document.createElement("div");
    card.className = "dd-assistant__complaint-summary";

    const totalNode = document.createElement("strong");
    totalNode.textContent = `${total} şikayet`;

    const detail = document.createElement("span");
    const latest = data.latest;

    if (
      latest
      && typeof latest === "object"
      && typeof latest.title === "string"
    ) {
      detail.textContent = (
        `Son kayıt: ${latest.title}`
      );
    } else {
      detail.textContent = (
        "Henüz kayıt bulunmuyor."
      );
    }

    card.append(
      totalNode,
      detail
    );

    return card;
  };

  const renderLinks = (links) => {
    if (
      !Array.isArray(links)
      || links.length === 0
    ) {
      return null;
    }

    const container = document.createElement("div");
    container.className = "dd-assistant__links";

    links.forEach((item) => {
      if (
        !item
        || typeof item !== "object"
        || typeof item.label !== "string"
        || !item.label.trim()
      ) {
        return;
      }

      const href = safeSameOriginPath(
        item.url
      );

      if (!href) {
        return;
      }

      const link = document.createElement("a");

      link.href = href;
      link.textContent = item.label;

      container.appendChild(
        link
      );
    });

    return (
      container.childElementCount
        ? container
        : null
    );
  };

  const appendAssistantResponse = (payload) => {
    const message = (
      payload
      && typeof payload.message === "string"
    )
      ? payload.message
      : "İşlem tamamlandı.";

    transcript.appendChild(
      makeBubble(
        message,
        "assistant"
      )
    );

    if (
      payload
      && payload.action === "MY_SUMMARY"
    ) {
      const summary = renderAccountSummary(
        payload.data
      );

      if (summary) {
        transcript.appendChild(
          summary
        );
      }
    }

    if (
      payload
      && payload.action === "MY_COMPLAINTS"
    ) {
      const summary = renderComplaintSummary(
        payload.data
      );

      if (summary) {
        transcript.appendChild(
          summary
        );
      }
    }

    const links = renderLinks(
      payload
        ? payload.links
        : null
    );

    if (links) {
      transcript.appendChild(
        links
      );
    }

    scrollTranscript();
  };

  const parseResponse = async (response) => {
    const contentType = (
      response.headers.get(
        "content-type"
      )
      || ""
    );

    if (
      !contentType.includes(
        "application/json"
      )
    ) {
      return null;
    }

    try {
      return await response.json();

    } catch (_error) {
      return null;
    }
  };

  const sendAction = async (
    action,
    label
  ) => {
    if (
      requestInFlight
      || typeof action !== "string"
      || !action
    ) {
      return;
    }

    appendUserMessage(
      label
    );

    setBusy(
      true
    );

    showTyping();

    const controller = new AbortController();

    const timeoutId = window.setTimeout(
      () => {
        controller.abort();
      },
      REQUEST_TIMEOUT_MS
    );

    try {
      const responsePromise = fetch(
        endpoint,
        {
          method: "POST",
          credentials: "same-origin",
          cache: "no-store",
          signal: controller.signal,
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRFToken": csrfInput.value,
          },
          body: JSON.stringify({
            action,
          }),
        }
      );

      const [response] = await Promise.all([
        responsePromise,
        wait(
          MIN_THINKING_MS
        ),
      ]);

      const payload = await parseResponse(
        response
      );

      removeTyping();

      if (!response.ok) {
        const message = (
          payload
          && typeof payload.message === "string"
        )
          ? payload.message
          : "Asistan isteği tamamlanamadı.";

        if (response.status === 429) {
          const retryAfter = response.headers.get(
            "Retry-After"
          );

          const suffix = retryAfter
            ? ` (${retryAfter} sn sonra tekrar deneyin.)`
            : "";

          appendError(
            `${message}${suffix}`
          );

          return;
        }

        appendError(
          message
        );

        return;
      }

      if (
        !payload
        || payload.ok !== true
      ) {
        appendError(
          "Asistan yanıtı doğrulanamadı."
        );

        return;
      }

      appendAssistantResponse(
        payload
      );

    } catch (error) {
      removeTyping();

      if (
        error
        && error.name === "AbortError"
      ) {
        appendError(
          "Asistan yanıt vermekte gecikti. Lütfen tekrar deneyin."
        );
      } else {
        appendError(
          "Bağlantı kurulamadı. Lütfen tekrar deneyin."
        );
      }

    } finally {
      window.clearTimeout(
        timeoutId
      );

      setBusy(
        false
      );
    }
  };

  toggle.addEventListener(
    "click",
    () => {
      setOpen(
        panel.hidden
      );
    }
  );

  closeButton.addEventListener(
    "click",
    () => {
      setOpen(
        false
      );
    }
  );

  actions.addEventListener(
    "click",
    (event) => {
      const button = event.target.closest(
        "[data-assistant-action]"
      );

      if (
        !button
        || !actions.contains(button)
      ) {
        return;
      }

      const action = (
        button.dataset.assistantAction
      );

      const strong = button.querySelector(
        "strong"
      );

      const label = strong
        ? strong.textContent.trim()
        : button.textContent.trim();

      sendAction(
        action,
        label
      );
    }
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (
        event.key === "Escape"
        && !panel.hidden
      ) {
        setOpen(
          false
        );
      }
    }
  );
})();

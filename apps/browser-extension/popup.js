const stateKey = "vaultUnifiedBrowserPairing";
const status = document.getElementById("status");
const pairForm = document.getElementById("pair-form");
const matchesElement = document.getElementById("matches");
const forget = document.getElementById("forget");

function setStatus(message, error = false) {
  status.textContent = message;
  status.className = error ? "error" : "";
}

async function sessionGet() {
  const result = await chrome.storage.session.get(stateKey);
  return result[stateKey] || null;
}

async function request(state, path, options = {}) {
  const response = await fetch(`${state.sidecarUrl}/api/browser${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Vault-Browser-Token": state.browserToken,
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Vault request failed");
  return body;
}

function normalizeAddress(value) {
  const url = new URL(value.trim());
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
    throw new Error("Use the local http://127.0.0.1 address shown by Vault Unified");
  }
  return url.href.replace(/\/$/, "");
}

function outcomeMessage(outcome) {
  switch (outcome.reason) {
    case "filled":
      return "Filled the visible login form.";
    case "ambiguous-password-fields":
      return "Multiple password fields or login forms were found. Nothing was filled.";
    case "new-password-flow":
      return "This looks like a password creation or change form. Nothing was filled.";
    case "iframe":
      return "The login form may be inside an iframe, which this version does not fill.";
    case "shadow-dom":
      return "The login form may use Shadow DOM, which this version does not fill.";
    case "empty-password":
      return "The selected entry has no password to fill.";
    default:
      return "No supported visible password field was found. Nothing was filled.";
  }
}

async function fillMatch(state, tab, entry) {
  try {
    setStatus("Fetching selected entry…");
    const values = await request(state, "/fill", {
      method: "POST",
      body: JSON.stringify({ entry_id: entry.id, url: tab.url }),
    });
    const injected = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: vaultUnifiedFillInputs,
      args: [values],
    });
    const outcome = injected[0]?.result || { reason: "no-password-field" };
    setStatus(outcomeMessage(outcome), outcome.reason !== "filled");
  } catch (error) {
    setStatus(error.message || String(error), true);
  }
}

async function showMatches(state) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !tab.url?.startsWith("http")) {
    setStatus("Open an http or https login page first.", true);
    return;
  }
  try {
    const result = await request(state, `/matches?url=${encodeURIComponent(tab.url)}`);
    matchesElement.replaceChildren();
    matchesElement.hidden = false;
    if (!result.matches.length) {
      setStatus("No saved login URL matches this page.");
      return;
    }
    setStatus("Choose an entry to fill.");
    for (const entry of result.matches) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "match";
      button.textContent = entry.title || "Untitled entry";
      const username = document.createElement("small");
      username.textContent = entry.username || "No username";
      button.append(username);
      button.addEventListener("click", () => void fillMatch(state, tab, entry));
      matchesElement.append(button);
    }
  } catch (error) {
    if (String(error.message || error).includes("locked") || String(error.message || error).includes("invalid")) {
      await chrome.storage.session.remove(stateKey);
      pairForm.hidden = false;
      forget.hidden = true;
    }
    setStatus(error.message || String(error), true);
  }
}

pairForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const sidecarUrl = normalizeAddress(document.getElementById("sidecar-url").value);
    const pairingCode = document.getElementById("pairing-code").value.trim();
    setStatus("Pairing…");
    const response = await fetch(`${sidecarUrl}/api/browser/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Vault-Browser-Pairing": pairingCode },
      body: "{}",
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Pairing failed");
    const state = { sidecarUrl, browserToken: body.browser_token };
    await chrome.storage.session.set({ [stateKey]: state });
    pairForm.hidden = true;
    forget.hidden = false;
    await showMatches(state);
  } catch (error) {
    setStatus(error.message || String(error), true);
  }
});

forget.addEventListener("click", async () => {
  await chrome.storage.session.remove(stateKey);
  matchesElement.hidden = true;
  forget.hidden = true;
  pairForm.hidden = false;
  setStatus("Pairing removed from this browser.");
});

void (async () => {
  const state = await sessionGet();
  if (!state) {
    pairForm.hidden = false;
    setStatus("Create a one-time pairing code in Vault Unified settings.");
    return;
  }
  forget.hidden = false;
  await showMatches(state);
})();

function vaultUnifiedFillInputs(values) {
  const visible = (input) => input && input.offsetParent !== null && !input.disabled && !input.readOnly;
  const visiblePasswords = [...document.querySelectorAll('input[type="password"]')].filter(visible);
  const hasIframe = document.querySelector("iframe") !== null;
  const hasShadowRoot = [...document.querySelectorAll("*")].some((element) => element.shadowRoot);

  if (visiblePasswords.length === 0) {
    return {
      username: false,
      password: false,
      reason: hasIframe ? "iframe" : hasShadowRoot ? "shadow-dom" : "no-password-field",
    };
  }
  if (visiblePasswords.length !== 1) {
    return { username: false, password: false, reason: "ambiguous-password-fields" };
  }

  const password = visiblePasswords[0];
  if ((password.autocomplete || "").toLowerCase() === "new-password") {
    return { username: false, password: false, reason: "new-password-flow" };
  }
  if (!values.password) {
    return { username: false, password: false, reason: "empty-password" };
  }

  const setValue = (input, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  };
  const scope = password.form || document;
  const usernameCandidates = [...scope.querySelectorAll(
    'input:not([type]), input[type="text"], input[type="email"], input[type="tel"]',
  )].filter((input) => visible(input) && (input.autocomplete || "").toLowerCase() !== "new-password");
  const explicitUsernames = usernameCandidates.filter((input) => {
    const autocomplete = (input.autocomplete || "").toLowerCase();
    return autocomplete === "username" || autocomplete === "email";
  });
  const username = explicitUsernames.length === 1
    ? explicitUsernames[0]
    : usernameCandidates.length === 1
      ? usernameCandidates[0]
      : null;

  if (username && values.username) setValue(username, values.username);
  setValue(password, values.password);
  return {
    username: Boolean(username && values.username),
    password: true,
    reason: "filled",
  };
}

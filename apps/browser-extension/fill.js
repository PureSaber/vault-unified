function vaultUnifiedFillInputs(values) {
  if (!values.pageOrigin || location.origin !== values.pageOrigin) {
    return { username: false, password: false, reason: "page-changed" };
  }
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
  const newPasswords = visiblePasswords.filter((input) => input.autocomplete.toLowerCase() === "new-password");
  const useNew = values.newPassword || (values.capture && newPasswords.length > 0);
  const targets = useNew ? newPasswords : visiblePasswords;
  const oneForm = visiblePasswords.every((input) => input.form === visiblePasswords[0].form);
  if (useNew && (targets.length === 0 || targets.length > 2 || !oneForm
      || (visiblePasswords.length > 1 && !visiblePasswords[0].form)
      || visiblePasswords.some((input) => !targets.includes(input) && input.autocomplete.toLowerCase() !== "current-password"))) {
    return { username: false, password: false, reason: "ambiguous-password-fields" };
  }
  if (!useNew && visiblePasswords.length !== 1) {
    return { username: false, password: false, reason: "ambiguous-password-fields" };
  }

  const password = targets[0];
  if (!useNew && !values.capture && (password.autocomplete || "").toLowerCase() === "new-password") {
    return { username: false, password: false, reason: "new-password-flow" };
  }
  if (!values.capture && !values.password) {
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

  if (values.capture) {
    if (!password.value) return { reason: "empty-password" };
    if (targets.some((input) => input.value !== password.value)) {
      return { reason: "ambiguous-password-fields" };
    }
    return { reason: "captured", username: username?.value || "", password: password.value };
  }

  if (username && values.username) setValue(username, values.username);
  targets.forEach((input) => setValue(input, values.password));
  return {
    username: Boolean(username && values.username),
    password: true,
    reason: useNew ? "new-filled" : "filled",
  };
}

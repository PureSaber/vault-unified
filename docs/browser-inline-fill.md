# Input-field account choice

Source implementation of personal-edition item 3. Published v1.3.0 remains the
previous popup-only release; use matching desktop and extension builds.

## Use

Enable **Choose accounts inside fields → Enable this website** in the extension.
Choose V beside a login input, then an account. Alt+Shift+V opens the chooser for
the focused input; arrows and Enter choose an account. Username-only steps fetch
only the username, password-only steps fetch only the password. Form companions
are filled only when unambiguous. Filling never submits a form. Explicit
one-time-code inputs offer TOTP accounts. Dynamic inputs and open Shadow DOM
forms use the same delegated focus handling.

The optional permission dialog is controlled by Chrome/Edge. Local preferences
also bind the exact origin including port, since browser permission patterns do
not distinguish ports. Users can authorize every HTTP/HTTPS website explicitly,
exclude individual websites, or revoke all optional website access.

## Boundaries

The background worker owns reconnect/discovery and authenticated API calls. A
content script never receives a browser token, signing key or master password.
The picker uses a closed Shadow DOM and accepts trusted user clicks. Metadata
is inserted as text. Deliveries carry a one-use nonce and target the initiating
document ID. Origin, permission, active tab and live target are rechecked before
delivery; target changes during page event handlers stop subsequent field writes.

Cross-origin frames require their own site authorization and an extension-owned
confirmation window. The window shows both origins and account metadata without
requesting a password. A confirmation lasts 60 seconds and is single-use. Cancel
immediately resets the frame picker. Only extension pages can change settings
or confirm these requests. Closing the window, revocation, navigation and expired
requests cannot obtain a password through the old confirmation.

No passive credential capture, automatic submission or webpage message bridge
is installed. Existing popup capture/save/change-password workflows remain
separate. The only new persistent extension value is non-secret site/language
preferences. No vault format changes are required.

## Validation

- Seven worker boundary tests exercise disabled sites, sender identity, document
  lifecycle, origin/port, navigation/revocation races, single-use/expired/cancelled
  frame consent and concurrent preference changes.
- Five new renderer journeys cover both languages, permission denial/revocation,
  frame confirmation errors, keyboard choice and closed picker behavior. Axe,
  generated screenshots and artifact scanning passed; the closed picker also
  has an accessible browser AX tree inspected by the journey.
- Actual isolated Chromium extension/native-host/API journey covers persistent
  reconnect, stepwise login, complex forms, synthetic-click refusal, target
  replacement, cross-origin cancel/confirm, OTP and revocation. This is distinct
  from the renderer mocks. Final installed Chrome/Edge acceptance remains in
  the delivery stage.

Acceptance: enable one website, fill each step of a login, choose the second of
two forms, cancel/approve a separately authorized embedded form, fill a code,
disable suggestions and confirm no picker remains. Lock the desktop during a
pending choice and confirm access is refused. Repeat using the browser shortcut.

Revert this increment to restore popup-only filling. Site preferences can remain
but remove optional permissions through browser extension settings. No vault
data rollback is needed.

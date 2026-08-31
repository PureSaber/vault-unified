# Vault Unified v1.3 product information architecture

## Audience and design rule

The default experience is for an individual who needs to save, find, copy, back up, and recover passwords without learning the implementation. The interface uses progressive disclosure in the place where a detail becomes relevant; it does not rely on a global simple/advanced mode.

Security controls remain in force when wording or navigation changes. Sync previews, destructive confirmations, encryption, authentication, automatic locking, and atomic writes are not optional usability trade-offs.

## Top-level navigation

An unlocked vault has exactly five permanent actions:

| Item | Beginner question it answers | Default content |
| --- | --- | --- |
| Passwords | Where are my passwords, and how do I add or find one? | Search, password list, **Add password**, contextual warnings |
| Security & recovery | Am I protected if I walk away or this computer fails? | Auto-lock, backup, restore, recovery package |
| Connections | Do I want to connect another password service? | One service card at a time, setup wizard, exceptional sync status |
| Settings | Which general preferences can I change? | Language, about, version |
| Lock now | How do I immediately protect the open vault? | Immediate lock, with unsaved-draft protection |

`Add`, `Sync`, and `Conflicts` are not permanent destinations. Adding starts from Passwords. Sync details are reached from Connections. Conflicts only appear through a contextual notice when conflicts exist.

## Passwords

- **Add password** is the primary page action; an empty vault says **Add first password**.
- A row opens its detail/editor. Copy password is the only permanent row action.
- Show password, copy username, edit, and delete live under **More actions**.
- Revealed passwords hide after 30 seconds, window/page focus loss, entry change, or navigation.
- Search is immediate. Responses are sequence-checked so an older response cannot replace a newer result.
- Healthy sync state and internal source markers are absent. Only waiting-to-sync, conflict, or error states produce human-readable context.

## Security & recovery

Auto-lock, encrypted backup, backup validation and restore, backup history, and the emergency recovery package share one destination. The page starts with conclusions and recommended actions. File paths, hashes, retention classes, and historical backup administration remain inside **Manage backup history** or a technical-details disclosure.

Three artifacts must remain distinct:

- Encrypted backup: routine recovery after device or file failure.
- Emergency recovery package: exceptional recovery or migration when ordinary access is unavailable.
- Plaintext export: a short-lived migration file, not a backup.

## Connections and sync

External services are optional and never block local vault creation. The default Connections page shows compact service cards. Selecting one service opens only that service's steps:

1. Check installation.
2. Configure.
3. Test.
4. Preview the first import without writing.
5. Confirm enablement.

Only one source is emphasized at a time. Environment-variable origins, command-line details, default sync location, and policy controls appear only after the user opens connection advanced settings. Normal background sync is quiet. Item-level sync review remains available on demand and remains mandatory before destructive execution.

## Contextual conflict flow

No conflict means no conflict entry. When conflicts exist, Passwords and Connections show: “N accounts were changed both on this device and in a connected service and need review.” The notice opens conflict resolution. Resolving or refreshing one conflict preserves unsubmitted choices on the other conflicts unless the user is explicitly warned before a reload.

## First run

Create and restore are the primary choices. Default copy says that passwords are encrypted on this device; it does not require knowledge of algorithms, format numbers, background processes, or storage internals. Those facts remain available under **Technical details**. Creating a vault opens the empty Passwords page and shows a non-blocking **No backup is set up yet** reminder. Connecting another service is not required.

## Internal routes and compatibility

The entry editor and conflict resolver remain internal application states rather than top-level navigation. Existing advanced entry types and connected-service metadata must remain readable without becoming default creation choices. Information-architecture changes do not migrate or rewrite vault data.

## Validation boundary

Renderer journeys verify that these routes and disclosures work with generated data. Packaged Windows smoke separately validates installed lifecycle behavior. Automated checks do not satisfy the final novice-research gate; the repository owner must review results from people who have not read the README and do not know password-manager internals.

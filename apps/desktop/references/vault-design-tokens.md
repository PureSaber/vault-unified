# Vault Unified — Design Tokens

Calm dark-mode palette for credential management (Bitwarden / 1Password bar).

## Surfaces

| Token | Value | Usage |
|-------|-------|--------|
| `--color-bg` | `#0f1419` | App background |
| `--color-surface` | `#151b24` | Cards, header |
| `--color-surface-raised` | `#1e2733` | Inputs, secondary buttons |
| `--color-surface-inset` | `#0c1016` | Conflict panels, code blocks |

## Borders

| Token | Value |
|-------|-------|
| `--color-border` | `#2a3441` |
| `--color-border-strong` | `#2f3b4a` |

## Text

| Token | Value | Usage |
|-------|-------|--------|
| `--color-text` | `#e7ecf3` | Primary text |
| `--color-text-secondary` | `#c5d0de` | Nav, labels |
| `--color-text-muted` | `#8b9bb4` | Meta, hints |
| `--color-text-faint` | `#6b7a90` | Timestamps |

## Accent & semantic

| Token | Value |
|-------|-------|
| `--color-accent` | `#2b6cb0` |
| `--color-accent-hover` | `#3182ce` |
| `--color-accent-muted` | `#243044` |
| `--color-success` | `#68d391` |
| `--color-error` | `#fc8181` |
| `--color-warning` | `#f6ad55` |

## Spacing & radius

- `--space-xs` 4px · `--space-sm` 8px · `--space-md` 12px · `--space-lg` 16px · `--space-xl` 24px
- `--radius-sm` 6px · `--radius-md` 8px · `--radius-lg` 12px
- Row min height: 48px (desktop click target)

## Motion

- `--duration-fast` 120ms · `--duration-normal` 180ms
- Respect `prefers-reduced-motion: reduce`

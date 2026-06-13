# Bab Console — Design System (V2 foundation)

Status: **Phase 0 spec**. This document defines the refreshed design system for the Bab
admin console. It is the source of truth; the live catalog at `/design-system` should
mirror it. It exists to fix the drift surfaced in the UI audit: divergent state-handling,
hard-coded status colors, four stat-tile implementations, two form idioms, no chart
primitive, and ~2900-line "god" screens.

## 1. Principles

1. **Tokens over literals.** No raw Tailwind palette colors (`emerald-*`, `amber-*`) in
   feature code — only semantic tokens. A status's color is decided once, centrally.
2. **One way to do a thing.** One table, one chart, one stat tile, one impact dialog, one
   filter toolbar, one detail-page shell, one form field. Variants, not reimplementations.
3. **States are first-class.** Every data surface ships loading (skeleton), empty, and
   error states by construction — never an ad-hoc `<p>Loading…</p>` or a silent fallthrough.
4. **Reference, don't reinvent.** `ProjectDetailPage` is the canonical detail-page shape
   (URL-synced tabs, decomposed sections, setup checklist). New work matches it.
5. **Dark-first, token-driven theming.** Keep the Tailwind-4 CSS-first pipeline in
   `src/index.css`; everything themeable flows from `:root` / `.dark` custom properties.

## 2. Token layer (foundation)

All in `src/index.css` (`:root` + `.dark`, re-exported via `@theme inline`).

### 2.1 Add — semantic status tokens (the highest-leverage fix)

The palette has only `primary/secondary/accent/destructive`. Add success / warning / info
so every healthy/degraded/expiring/blocked state is tokenized. Proposed oklch:

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `--success` / `--success-foreground` | `0.62 0.15 150` / `1 0 0` | `0.68 0.15 150` / `0.18 0.02 150` | active, ready, healthy, 2xx |
| `--warning` / `--warning-foreground` | `0.78 0.16 75` / `0.28 0.05 75` | `0.80 0.15 75` / `0.24 0.04 75` | degraded, expiring, needs-action |
| `--info` / `--info-foreground` | `0.62 0.13 255` / `1 0 0` | `0.66 0.12 255` / `0.18 0.02 255` | informational, dry-run, neutral-notice |

(`destructive` already covers error/revoked/expired; `muted` covers inactive/unknown.)
Re-export in `@theme inline` as `--color-success`, `--color-success-foreground`, etc. Then
refactor `StatusBadge`/`HttpStatusBadge` and the 8 `emerald/amber` files onto them.

### 2.2 Add — type scale tokens

Tokenize the ladder (today it's illustrated, not enforced) so screens can't drift:

```
--text-display: 1.875rem/600   (page hero)      → replaces ad-hoc text-3xl
--text-h1:      1.5rem/600      (PageHeader)
--text-h2:      1.25rem/600     (section)
--text-title:   1rem/500        (card title)
--text-body:    0.875rem/400    (body, tables, forms)
--text-caption: 0.75rem/400     (meta, muted)
--text-code:    0.75rem mono    (ids, slugs)
```

### 2.3 Fix — token hygiene

- Install `@fontsource/jetbrains-mono` (the `--font-mono` token references it but it isn't
  loaded → silent fallback), **or** drop the mono token. Remove the unused `Source Serif 4`
  token and the orphaned `@fontsource-variable/geist` dependency.
- Regenerate the shadow ramp: `--shadow-2xs`/`--shadow-xs` are identical and `--shadow-2xl`
  is weaker than `--shadow-xl`; wire the oklch shadow primitives through or drop them.
- Reconcile the neutral ramp: light `--muted` is a warm beige off-key against the cool grays.

## 3. Component layers

### Layer 1 — Primitives (`components/ui/`)
Keep the 26 shadcn primitives. **Add:** `chart` (recharts wrapper, consumes `--chart-*`),
`data-table`, `form`/`form-field`, `password-input`, `pagination`, `progress`, `avatar`,
`radio-group`, `segmented-control` (or standardize on `ToggleGroup variant="line"`),
`callout` (alias the existing unused `alert`), `copyable-id`.

### Layer 2 — Composites (`shared/components/`)
`StatCard` (kills the `Fact`/`MetricCard`/`Stat`/`ImpactCount` divergence),
`FilterToolbar` (+ active-filter chips), `ImpactConfirmationDialog` (canonicalize the
Policies `useImpactConfirmation` pattern; retire `window.confirm` in Guardrails),
`SecretRevealDialog`, `MembersCard` (Team≈Project), `EntityPicker` (replace raw UUID inputs),
`ModelMultiselect`, `MessageStateCard` (forbidden/no-access/error/coming-soon converge),
`MetricBar` (progress).

### Layer 3 — Page templates (`shared/templates/`)
`ResourceListPage` (Teams≈Projects: header + count + search + segment + responsive
table/cards + edit sheet), `DetailPage` (tabbed, generalize `ProjectDetailPage`),
`SettingsForm`, `Dashboard`, `AuthCard`.

### Shared lib (`shared/lib/`)
Extract the duplicated helpers: `formatCents` (one version), `formatRole*`, `shortId`,
`useDebouncedValue`, `buildDateRange`/`DateRangePopover`, currency/relative-time formatters.

## 4. Adoption plan (after the foundation lands)

Order by impact + decomposition payoff, all matched to the `ProjectDetailPage` reference:

1. **Usage** — adopt `Chart` + `DataTable` + `StatCard` (this PoC).
2. **Guardrails** — decompose the 1872-line monolith; `ImpactConfirmationDialog` replaces
   `window.confirm`; `DataTable` + `FilterToolbar`.
3. **Providers `ResourcesPanel`** — split the 2858-line file; `DataTable` everywhere.
4. **Policies** — unify the two near-identical detail pages into `DetailPage`; dedupe the
   model-multiselect + draft builders.
5. **Activity / Audit** — shared `FilterToolbar` + chips + one event-detail component.
6. Teams / Projects / Virtual-keys / Users / Settings — templates + shared composites.

## 5. The two primitives built now (PoC)

- **`DataTable<T>`** (`components/ui/data-table.tsx`): column config + built-in `loading`
  (skeleton rows), `empty` (EmptyState), and `error` (retry) states, optional pagination
  footer and row click. Replaces the ~12 per-table reimplementations.
- **`Chart`** (`components/ui/chart.tsx`): a recharts wrapper (`ChartContainer` +
  `ChartTooltip`) driven by the existing `--chart-1..5` tokens, with axes, grid, tooltip,
  and legend — replacing the three hand-rolled `div`-bar implementations. Proven on the
  Usage trend (which today renders an empty dark block despite real data).
</content>

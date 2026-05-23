import { Caption, Example, Section } from "../components/Section";

const semanticColors = [
  { name: "background", description: "App background" },
  { name: "foreground", description: "Default text" },
  { name: "card", description: "Card surface" },
  { name: "card-foreground", description: "Text on card" },
  { name: "popover", description: "Popover surface" },
  { name: "popover-foreground", description: "Text on popover" },
  { name: "primary", description: "Primary brand" },
  { name: "primary-foreground", description: "Text on primary" },
  { name: "secondary", description: "Secondary brand" },
  { name: "secondary-foreground", description: "Text on secondary" },
  { name: "muted", description: "Muted background" },
  { name: "muted-foreground", description: "Muted text" },
  { name: "accent", description: "Accent fill" },
  { name: "accent-foreground", description: "Text on accent" },
  { name: "destructive", description: "Danger / destructive" },
  { name: "destructive-foreground", description: "Text on destructive" },
  { name: "border", description: "Default border" },
  { name: "input", description: "Form input border" },
  { name: "ring", description: "Focus ring" },
];

const chartColors = ["chart-1", "chart-2", "chart-3", "chart-4", "chart-5"];

const radiusScale = [
  { name: "sm", token: "--radius-sm" },
  { name: "md", token: "--radius-md" },
  { name: "lg", token: "--radius-lg" },
  { name: "xl", token: "--radius-xl" },
  { name: "2xl", token: "--radius-2xl" },
  { name: "3xl", token: "--radius-3xl" },
  { name: "4xl", token: "--radius-4xl" },
];

const shadowScale = [
  { name: "2xs", className: "shadow-2xs" },
  { name: "xs", className: "shadow-xs" },
  { name: "sm", className: "shadow-sm" },
  { name: "md", className: "shadow-md" },
  { name: "lg", className: "shadow-lg" },
  { name: "xl", className: "shadow-xl" },
  { name: "2xl", className: "shadow-2xl" },
];

const spacingScale = [1, 2, 3, 4, 6, 8, 12, 16, 24];

export function FoundationsSection() {
  return (
    <Section
      id="foundations"
      title="Foundations"
      description="Theme tokens defined by themecn on top of shadcn. Everything below is wired to CSS custom properties, so a theme switch propagates app-wide."
    >
      <Example
        label="Semantic colors"
        description="Names match the Tailwind utilities — e.g. bg-primary, text-muted-foreground."
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {semanticColors.map((color) => (
            <ColorSwatch key={color.name} name={color.name} description={color.description} />
          ))}
        </div>
      </Example>

      <Example
        label="Chart palette"
        description="Use these for data viz (sequential or categorical)."
      >
        <div className="flex flex-wrap gap-3">
          {chartColors.map((name) => (
            <div key={name} className="flex flex-col items-center gap-2">
              <div
                className="size-16 rounded-md border"
                style={{ backgroundColor: `var(--${name})` }}
                aria-hidden="true"
              />
              <Caption>{name}</Caption>
            </div>
          ))}
        </div>
      </Example>

      <Example label="Typography" description="Poppins for UI, JetBrains Mono for code/tokens.">
        <div className="space-y-4">
          <div>
            <p className="text-3xl font-semibold tracking-tight">The quick brown fox</p>
            <Caption>text-3xl · font-semibold · tracking-tight</Caption>
          </div>
          <div>
            <p className="text-2xl font-semibold tracking-tight">The quick brown fox</p>
            <Caption>text-2xl · font-semibold · tracking-tight (PageHeader)</Caption>
          </div>
          <div>
            <p className="text-xl font-semibold tracking-tight">The quick brown fox</p>
            <Caption>text-xl · font-semibold (section heading)</Caption>
          </div>
          <div>
            <p className="text-base font-medium">The quick brown fox</p>
            <Caption>text-base · font-medium (card title)</Caption>
          </div>
          <div>
            <p className="text-sm">
              The quick brown fox jumps over the lazy dog. Body copy lives at this size for tables,
              forms, and descriptions.
            </p>
            <Caption>text-sm (body)</Caption>
          </div>
          <div>
            <p className="text-sm text-muted-foreground">
              The quick brown fox jumps over the lazy dog.
            </p>
            <Caption>text-sm · text-muted-foreground (secondary)</Caption>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">
              The quick brown fox jumps over the lazy dog.
            </p>
            <Caption>text-xs · text-muted-foreground (captions, meta)</Caption>
          </div>
          <div>
            <p className="font-mono text-xs text-muted-foreground">
              vk_8a4f9d_2cbe1a · slug-or-id-like
            </p>
            <Caption>font-mono · text-xs (slugs, IDs, code)</Caption>
          </div>
        </div>
      </Example>

      <Example label="Radius" description="Corner rounding scale. Buttons use md, cards use xl.">
        <div className="flex flex-wrap items-end gap-4">
          {radiusScale.map((entry) => (
            <div key={entry.name} className="flex flex-col items-center gap-2">
              <div
                className="size-16 border bg-muted"
                style={{ borderRadius: `var(${entry.token})` }}
                aria-hidden="true"
              />
              <Caption>{entry.name}</Caption>
            </div>
          ))}
        </div>
      </Example>

      <Example label="Shadows">
        <div className="flex flex-wrap items-end gap-4">
          {shadowScale.map((entry) => (
            <div key={entry.name} className="flex flex-col items-center gap-2">
              <div className={`size-16 rounded-md bg-card ${entry.className}`} aria-hidden="true" />
              <Caption>{entry.name}</Caption>
            </div>
          ))}
        </div>
      </Example>

      <Example
        label="Spacing"
        description="Tailwind spacing scale × 0.25rem. Reach for gap-2 / gap-3 / gap-4 / gap-6 most often."
      >
        <div className="space-y-2">
          {spacingScale.map((unit) => (
            <div key={unit} className="flex items-center gap-3 text-xs">
              <div
                className="h-3 rounded-sm bg-primary"
                style={{ width: `calc(var(--spacing) * ${unit})` }}
                aria-hidden="true"
              />
              <span className="font-mono text-muted-foreground">gap-{unit}</span>
              <span className="text-muted-foreground">{unit * 0.25}rem</span>
            </div>
          ))}
        </div>
      </Example>
    </Section>
  );
}

function ColorSwatch({ name, description }: { name: string; description: string }) {
  return (
    <div className="flex items-center gap-3 rounded-md border p-2">
      <div
        className="size-10 shrink-0 rounded-md border"
        style={{ backgroundColor: `var(--${name})` }}
        aria-hidden="true"
      />
      <div className="min-w-0">
        <p className="truncate font-mono text-xs">{name}</p>
        <p className="truncate text-xs text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

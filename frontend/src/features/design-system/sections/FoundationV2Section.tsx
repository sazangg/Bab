import { Activity, Plug, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FilterToolbar } from "@/shared/components/FilterToolbar";
import { ImpactConfirmationDialog } from "@/shared/components/ImpactConfirmationDialog";
import { MessageStateCard } from "@/shared/components/MessageStateCard";
import { StatCard } from "@/shared/components/StatCard";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { Caption, Example, Section } from "../components/Section";

const TYPE_SCALE: [string, string][] = [
  ["text-display", "Display"],
  ["text-h1", "Heading 1"],
  ["text-h2", "Heading 2"],
  ["text-title", "Title"],
  ["text-body", "Body"],
  ["text-caption", "Caption"],
];

const STATUS_TOKENS = ["success", "warning", "info"];

function ImpactDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="destructive" onClick={() => setOpen(true)}>
        Archive team…
      </Button>
      <ImpactConfirmationDialog
        open={open}
        onOpenChange={setOpen}
        title="Archive Platform Engineering?"
        description="Descendant gateway traffic stops immediately; history is preserved."
        confirmLabel="Archive team"
        onConfirm={() => setOpen(false)}
      >
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div className="rounded-md border bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">Projects affected</div>
            <div className="font-medium tabular-nums">3</div>
          </div>
          <div className="rounded-md border bg-muted/20 p-3">
            <div className="text-xs text-muted-foreground">Virtual keys affected</div>
            <div className="font-medium tabular-nums">7</div>
          </div>
        </div>
      </ImpactConfirmationDialog>
    </>
  );
}

export function FoundationV2Section() {
  return (
    <Section
      id="foundation-v2"
      title="Foundation v2 (new)"
      description="Semantic status tokens, the tokenized type scale, and the shared composites introduced by the design-system refresh."
    >
      <Example
        label="Semantic status tokens"
        description="success / warning / info join primary/secondary/accent/destructive — no more raw emerald/amber in feature code."
      >
        <div className="flex flex-wrap items-center gap-5">
          {STATUS_TOKENS.map((token) => (
            <div key={token} className="flex items-center gap-2">
              <span
                className="size-6 rounded-md border border-border"
                style={{ background: `var(--${token})` }}
              />
              <Caption>{token}</Caption>
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <StatusBadge variant="success">Active</StatusBadge>
          <StatusBadge variant="warning">Degraded</StatusBadge>
          <StatusBadge variant="info">Dry run</StatusBadge>
          <StatusBadge variant="error">Revoked</StatusBadge>
          <StatusBadge variant="muted">Inactive</StatusBadge>
        </div>
      </Example>

      <Example
        label="Type scale"
        description="Tokenized so screens can't drift: text-display / h1 / h2 / title / body / caption / code."
      >
        <div className="space-y-2">
          {TYPE_SCALE.map(([className, name]) => (
            <div key={className} className={`${className} font-semibold`}>
              {name} — The quick brown fox
            </div>
          ))}
          <div className="text-code font-mono text-muted-foreground">
            text-code — bab-sk-697affb5a (JetBrains Mono)
          </div>
        </div>
      </Example>

      <Example
        label="StatCard"
        description="One stat tile replacing the Fact / MetricCard / Stat / ImpactCount divergence."
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label="Requests" value="463" hint="last 20 days" icon={Activity} />
          <StatCard label="Spend" value="$5.87" hint="reported usage" icon={Plug} />
          <StatCard label="Error rate" value="9.1%" />
        </div>
      </Example>

      <Example label="FilterToolbar + active-filter chips">
        <FilterToolbar
          chips={[
            { key: "model", label: "Model: gpt-4o", onRemove: () => {} },
            { key: "status", label: "Status: 429", onRemove: () => {} },
          ]}
          onClearAll={() => {}}
        >
          <Input className="h-8 w-56" placeholder="Search…" />
          <Button variant="outline" size="sm">
            Model
          </Button>
          <Button variant="outline" size="sm">
            Status
          </Button>
        </FilterToolbar>
      </Example>

      <Example
        label="ImpactConfirmationDialog"
        description="Impact-gated destructive confirm; replaces window.confirm and 3 bespoke dialogs."
      >
        <ImpactDemo />
      </Example>

      <Example
        label="MessageStateCard"
        description="Forbidden / no-access / error / coming-soon states converge here."
      >
        <MessageStateCard
          icon={ShieldAlert}
          tone="destructive"
          fillViewport={false}
          title="Access denied"
          description="You don't have permission to view this surface."
          action={
            <Button variant="outline" size="sm">
              Go to your workspace
            </Button>
          }
        />
      </Example>
    </Section>
  );
}

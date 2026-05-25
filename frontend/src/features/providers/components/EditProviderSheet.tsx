import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronDown, ChevronUp, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { useGetSettingsApiV1SettingsGet } from "@/shared/api/generated/settings/settings";
import type { ProviderResponse, UpdateProviderRequest } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import {
  buildProviderUpdatePayload,
  mergeCircuitBreakerPolicy,
  mergeFallbackPolicy,
  mergeRetryPolicy,
} from "../lib/policy";
import {
  defaultCircuitBreakerPolicy,
  defaultFallbackPolicy,
  defaultRetryPolicy,
  editProviderSchema,
  STATUS_CODE_MAX,
  STATUS_CODE_MIN,
  type EditProviderInput,
  type EditProviderValues,
  type RetryPolicyValues,
} from "../lib/schemas";

export function EditProviderSheet({
  provider,
  onClose,
  onSubmit,
  isPending,
}: {
  provider: ProviderResponse | null;
  onClose: () => void;
  onSubmit: (data: UpdateProviderRequest) => void;
  isPending: boolean;
}) {
  const form = useForm<EditProviderInput, unknown, EditProviderValues>({
    resolver: zodResolver(editProviderSchema),
    defaultValues: {
      name: "",
      slug: "",
      base_url: "",
      description: "",
      request_timeout_seconds: undefined,
      max_body_bytes_kb: undefined,
      max_concurrent_requests: undefined,
      model_sync_mode: "inherit",
      retry_policy: defaultRetryPolicy,
      fallback_policy: defaultFallbackPolicy,
      circuit_breaker_policy: defaultCircuitBreakerPolicy,
    },
  });
  const retryPolicy = useWatch({ control: form.control, name: "retry_policy" });
  const fallbackPolicy = useWatch({ control: form.control, name: "fallback_policy" });
  const modelSyncMode = useWatch({ control: form.control, name: "model_sync_mode" });
  const circuitBreakerPolicy = useWatch({
    control: form.control,
    name: "circuit_breaker_policy",
  });

  const providersQuery = useListProvidersApiV1ProvidersGet();
  const settingsQuery = useGetSettingsApiV1SettingsGet();
  const settings = settingsQuery.data?.status === 200 ? settingsQuery.data.data : null;
  const otherProviders =
    providersQuery.data?.status === 200
      ? providersQuery.data.data.filter((item) => item.id !== provider?.id && item.is_active)
      : [];

  useEffect(() => {
    if (!provider) return;
    form.reset({
      name: provider.name,
      slug: provider.slug ?? "",
      base_url: provider.base_url,
      description: provider.description ?? "",
      request_timeout_seconds: provider.request_timeout_seconds ?? undefined,
      max_body_bytes_kb:
        provider.max_body_bytes != null
          ? Math.max(1, Math.round(provider.max_body_bytes / 1024))
          : undefined,
      max_concurrent_requests: provider.max_concurrent_requests ?? undefined,
      model_sync_mode: parseModelSyncMode(provider.model_sync_mode),
      retry_policy: mergeRetryPolicy(provider.retry_policy),
      fallback_policy: mergeFallbackPolicy(provider.fallback_policy),
      circuit_breaker_policy: mergeCircuitBreakerPolicy(provider.circuit_breaker_policy),
    });
  }, [provider, form]);

  const submit = form.handleSubmit((values) => onSubmit(buildProviderUpdatePayload(values)));

  return (
    <Sheet open={Boolean(provider)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit provider</SheetTitle>
          <SheetDescription>
            Identity, routing, request controls, and resilience policies. Credentials are managed on
            the detail page.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <form className="grid gap-6" onSubmit={submit}>
            <FormSection title="Identity">
              <FormField
                label="Name"
                htmlFor="edit-provider-name"
                error={form.formState.errors.name?.message}
              >
                <Input id="edit-provider-name" {...form.register("name")} />
              </FormField>
              <FormField label="Slug" htmlFor="edit-provider-slug">
                <Input id="edit-provider-slug" {...form.register("slug")} />
              </FormField>
              <FormField
                label="Base URL"
                htmlFor="edit-provider-base-url"
                error={form.formState.errors.base_url?.message}
              >
                <Input id="edit-provider-base-url" {...form.register("base_url")} />
              </FormField>
              <FormField
                label="Description"
                htmlFor="edit-provider-description"
                hint="Optional. Shown on the provider summary."
              >
                <Textarea
                  id="edit-provider-description"
                  rows={3}
                  {...form.register("description")}
                />
              </FormField>
            </FormSection>

            <Separator />

            <FormSection
              title="Request controls"
              description="Per-request controls inherit gateway defaults when blank."
            >
              <FormField
                label="Request timeout (seconds)"
                htmlFor="edit-provider-timeout"
                hint={`Blank inherits org default (${settings?.default_request_timeout_seconds ?? 30}s).`}
                error={form.formState.errors.request_timeout_seconds?.message}
              >
                <Input
                  id="edit-provider-timeout"
                  type="number"
                  min={1}
                  max={300}
                  placeholder="Inherited"
                  {...form.register("request_timeout_seconds")}
                />
              </FormField>
              <div className="grid grid-cols-2 gap-3">
                <FormField
                  label="Max body (KB)"
                  htmlFor="edit-provider-body"
                  hint={`Blank inherits org default (${Math.round((settings?.default_max_body_bytes ?? 0) / 1024).toLocaleString()} KB).`}
                >
                  <Input
                    id="edit-provider-body"
                    type="number"
                    min={1}
                    placeholder="—"
                    {...form.register("max_body_bytes_kb")}
                  />
                </FormField>
                <FormField
                  label="Max concurrent requests"
                  htmlFor="edit-provider-concurrent"
                  hint="Blank = no cap"
                >
                  <Input
                    id="edit-provider-concurrent"
                    type="number"
                    min={1}
                    placeholder="—"
                    {...form.register("max_concurrent_requests")}
                  />
                </FormField>
              </div>
              <FormField label="Model sync mode" htmlFor="edit-provider-model-sync">
                <Select
                  value={modelSyncMode}
                  onValueChange={(value) =>
                    form.setValue(
                      "model_sync_mode",
                      value as "inherit" | "merge" | "replace" | "disabled",
                    )
                  }
                >
                  <SelectTrigger id="edit-provider-model-sync">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="inherit">
                      Inherit org default ({settings?.default_model_sync_mode ?? "merge"})
                    </SelectItem>
                    <SelectItem value="merge">Merge</SelectItem>
                    <SelectItem value="replace">Replace</SelectItem>
                    <SelectItem value="disabled">Disabled</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
            </FormSection>

            <Separator />

            <PolicySection
              title="Retry policy"
              description="Retry against the same provider with backoff when upstream errors occur."
              enabled={retryPolicy?.enabled ?? false}
              onEnabledChange={(checked) => form.setValue("retry_policy.enabled", checked)}
            >
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Max attempts" htmlFor="edit-retry-attempts">
                  <Input
                    id="edit-retry-attempts"
                    type="number"
                    min={1}
                    max={10}
                    {...form.register("retry_policy.max_attempts", { valueAsNumber: true })}
                  />
                </FormField>
                <FormField label="Backoff" htmlFor="edit-retry-backoff">
                  <Select
                    value={retryPolicy?.backoff ?? defaultRetryPolicy.backoff}
                    onValueChange={(value) =>
                      form.setValue("retry_policy.backoff", value as RetryPolicyValues["backoff"])
                    }
                  >
                    <SelectTrigger id="edit-retry-backoff">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="constant">Constant</SelectItem>
                      <SelectItem value="linear">Linear</SelectItem>
                      <SelectItem value="exponential">Exponential</SelectItem>
                    </SelectContent>
                  </Select>
                </FormField>
                <FormField label="Initial delay (ms)" htmlFor="edit-retry-initial">
                  <Input
                    id="edit-retry-initial"
                    type="number"
                    min={0}
                    {...form.register("retry_policy.initial_delay_ms", { valueAsNumber: true })}
                  />
                </FormField>
                <FormField label="Max delay (ms)" htmlFor="edit-retry-max">
                  <Input
                    id="edit-retry-max"
                    type="number"
                    min={0}
                    {...form.register("retry_policy.max_delay_ms", { valueAsNumber: true })}
                  />
                </FormField>
              </div>
              <FormField
                label="Retry on status codes"
                hint="Press Enter or comma to add. Click × to remove."
              >
                <StatusCodeChipInput
                  values={retryPolicy?.retry_on_status ?? []}
                  onChange={(next) => form.setValue("retry_policy.retry_on_status", next)}
                  defaults={defaultRetryPolicy.retry_on_status}
                />
              </FormField>
            </PolicySection>

            <Separator />

            <PolicySection
              title="Fallback policy"
              description="Route to other configured providers in order when this provider keeps failing."
              enabled={fallbackPolicy?.enabled ?? false}
              onEnabledChange={(checked) => form.setValue("fallback_policy.enabled", checked)}
            >
              <FormField
                label="Trigger on status codes"
                hint="Fallback fires when any of these statuses come back."
              >
                <StatusCodeChipInput
                  values={fallbackPolicy?.trigger_on_status ?? []}
                  onChange={(next) => form.setValue("fallback_policy.trigger_on_status", next)}
                  defaults={defaultFallbackPolicy.trigger_on_status}
                />
              </FormField>
              <FormField label="Fallback providers" hint="Tried in order. Reorder with the arrows.">
                <FallbackProviderPicker
                  selected={fallbackPolicy?.fallback_provider_ids ?? []}
                  available={otherProviders}
                  onChange={(next) => form.setValue("fallback_policy.fallback_provider_ids", next)}
                />
              </FormField>
            </PolicySection>

            <Separator />

            <PolicySection
              title="Circuit breaker"
              description="Trip when failures cluster, then refuse traffic for a cooldown so upstream can recover."
              enabled={circuitBreakerPolicy?.enabled ?? false}
              onEnabledChange={(checked) =>
                form.setValue("circuit_breaker_policy.enabled", checked)
              }
            >
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Failure threshold (%)" htmlFor="edit-cb-pct">
                  <Input
                    id="edit-cb-pct"
                    type="number"
                    min={0}
                    max={100}
                    {...form.register("circuit_breaker_policy.failure_threshold_pct", {
                      valueAsNumber: true,
                    })}
                  />
                </FormField>
                <FormField label="Min requests" htmlFor="edit-cb-min">
                  <Input
                    id="edit-cb-min"
                    type="number"
                    min={0}
                    {...form.register("circuit_breaker_policy.min_request_count", {
                      valueAsNumber: true,
                    })}
                  />
                </FormField>
                <FormField label="Window (seconds)" htmlFor="edit-cb-window">
                  <Input
                    id="edit-cb-window"
                    type="number"
                    min={1}
                    {...form.register("circuit_breaker_policy.window_seconds", {
                      valueAsNumber: true,
                    })}
                  />
                </FormField>
                <FormField label="Cooldown (seconds)" htmlFor="edit-cb-cooldown">
                  <Input
                    id="edit-cb-cooldown"
                    type="number"
                    min={1}
                    {...form.register("circuit_breaker_policy.cooldown_seconds", {
                      valueAsNumber: true,
                    })}
                  />
                </FormField>
              </div>
            </PolicySection>
          </form>
        </div>
        <SheetFooter>
          <Button type="submit" disabled={isPending} onClick={submit}>
            {isPending ? "Saving..." : "Save changes"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

export function FormSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="space-y-0.5">
        <h3 className="text-sm font-medium">{title}</h3>
        {description ? <p className="text-xs text-muted-foreground">{description}</p> : null}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

export function FormField({
  label,
  htmlFor,
  error,
  hint,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? <p className="text-xs text-destructive">{error}</p> : null}
    </div>
  );
}

function PolicySection({
  title,
  description,
  enabled,
  onEnabledChange,
  children,
}: {
  title: string;
  description: string;
  enabled: boolean;
  onEnabledChange: (checked: boolean) => void;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <h3 className="text-sm font-medium">{title}</h3>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={onEnabledChange}
          aria-label={`Enable ${title.toLowerCase()}`}
        />
      </div>
      <div
        className={cn("space-y-3 transition-opacity", !enabled && "pointer-events-none opacity-50")}
        aria-hidden={!enabled}
      >
        {children}
      </div>
    </section>
  );
}

function StatusCodeChipInput({
  values,
  onChange,
  defaults,
}: {
  values: number[];
  onChange: (next: number[]) => void;
  defaults: number[];
}) {
  const [draft, setDraft] = useState("");
  const addCode = (raw: string) => {
    const code = Number.parseInt(raw.trim(), 10);
    if (!Number.isFinite(code)) return;
    if (code < STATUS_CODE_MIN || code > STATUS_CODE_MAX) return;
    if (values.includes(code)) return;
    onChange([...values, code].sort((a, b) => a - b));
  };
  const sortedDefaults = [...defaults].sort((a, b) => a - b);
  const matchesDefaults =
    values.length === sortedDefaults.length &&
    values.every((value, index) => value === sortedDefaults[index]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex min-h-7 flex-wrap items-center gap-1.5">
        {values.length === 0 ? (
          <span className="text-xs text-muted-foreground">No codes set.</span>
        ) : null}
        {values.map((code) => (
          <span
            key={code}
            className="inline-flex items-center gap-1 rounded-md border bg-muted/40 px-2 py-0.5 font-mono text-xs"
          >
            {code}
            <button
              type="button"
              className="rounded-sm text-muted-foreground hover:text-foreground"
              onClick={() => onChange(values.filter((value) => value !== code))}
              aria-label={`Remove ${code}`}
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <Input
          inputMode="numeric"
          placeholder="e.g. 503"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              addCode(draft);
              setDraft("");
            }
          }}
          className="max-w-28"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => {
            addCode(draft);
            setDraft("");
          }}
          disabled={!draft.trim()}
        >
          Add
        </Button>
        {!matchesDefaults ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => onChange([...sortedDefaults])}
          >
            Reset
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function FallbackProviderPicker({
  selected,
  available,
  onChange,
}: {
  selected: string[];
  available: ProviderResponse[];
  onChange: (next: string[]) => void;
}) {
  if (available.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
        Add another active provider to enable fallback routing.
      </p>
    );
  }
  const move = (index: number, direction: -1 | 1) => {
    const next = [...selected];
    const target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };
  const remaining = available.filter((provider) => !selected.includes(provider.id));
  return (
    <div className="space-y-2">
      {selected.length > 0 ? (
        <ol className="space-y-1.5 rounded-md border p-2">
          {selected.map((id, index) => {
            const provider = available.find((item) => item.id === id);
            const label = provider?.name ?? "Unknown provider";
            return (
              <li
                key={id}
                className="flex items-center justify-between rounded-md bg-muted/40 px-2 py-1.5"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <span className="w-5 font-mono text-xs text-muted-foreground">{index + 1}</span>
                  <span className="truncate text-sm">{label}</span>
                  {!provider ? <StatusBadge variant="error">Missing</StatusBadge> : null}
                </div>
                <div className="flex items-center gap-0.5">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Move up"
                    disabled={index === 0}
                    onClick={() => move(index, -1)}
                  >
                    <ChevronUp />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Move down"
                    disabled={index === selected.length - 1}
                    onClick={() => move(index, 1)}
                  >
                    <ChevronDown />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-sm"
                    aria-label="Remove"
                    onClick={() => onChange(selected.filter((value) => value !== id))}
                  >
                    <X />
                  </Button>
                </div>
              </li>
            );
          })}
        </ol>
      ) : null}
      {remaining.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {remaining.map((provider) => (
            <Button
              type="button"
              key={provider.id}
              variant="outline"
              size="sm"
              onClick={() => onChange([...selected, provider.id])}
            >
              <Plus />
              {provider.name}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function parseModelSyncMode(value: string | null | undefined) {
  if (value === "merge" || value === "replace" || value === "disabled") return value;
  return "inherit";
}

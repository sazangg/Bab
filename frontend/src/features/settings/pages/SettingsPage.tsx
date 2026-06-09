import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { ImageIcon, Save, Settings, Upload } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useRef } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { hasPermission } from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import {
  useGetSettingsApiV1SettingsGet,
  useUpdateSettingsApiV1SettingsPatch,
  useUploadOrganizationLogoApiV1SettingsOrganizationLogoPost,
} from "@/shared/api/generated/settings/settings";
import type { UpdateOrganizationSettingsRequest } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { PageHeader } from "@/shared/components/PageHeader";

const settingsSchema = z.object({
  organization_name: z.string().min(1).max(255),
  public_app_url: z.preprocess(
    (value) => (typeof value === "string" ? value.trim() : value),
    z
      .string()
      .max(500)
      .refine((value) => value === "" || isAbsoluteHttpUrl(value), {
        message: "Enter an absolute http:// or https:// app URL.",
      })
      .transform((value) => value.replace(/\/$/, ""))
      .optional(),
  ),
  public_base_url: z.preprocess(
    (value) => (typeof value === "string" ? value.trim() : value),
    z
      .string()
      .max(500)
      .refine((value) => value === "" || isAbsoluteHttpUrl(value), {
        message: "Enter an absolute http:// or https:// gateway URL.",
      })
      .transform((value) => value.replace(/\/$/, ""))
      .optional(),
  ),
  default_request_timeout_seconds: z.coerce.number().int().min(1).max(300),
  default_retry_count: z.coerce.number().int().min(0).max(10),
  default_max_body_bytes: z.coerce.number().int().min(1024).max(100_000_000),
  default_model_sync_mode: z.enum(["merge", "replace", "disabled"]),
  default_virtual_key_expiration_days: z.preprocess(
    optionalNumber,
    z.number().int().min(1).max(3650).optional(),
  ),
  virtual_key_prefix: z.string().min(1).max(32),
  allow_secret_copy: z.boolean(),
});

type SettingsInput = z.input<typeof settingsSchema>;
type SettingsValues = z.output<typeof settingsSchema>;

export function SettingsPage() {
  const queryClient = useQueryClient();
  const logoInputRef = useRef<HTMLInputElement | null>(null);
  const settingsQuery = useGetSettingsApiV1SettingsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const settings = settingsQuery.data?.status === 200 ? settingsQuery.data.data : undefined;
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const canManageSettings = hasPermission(currentUser, "settings.manage");
  const form = useForm<SettingsInput, unknown, SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      organization_name: "",
      public_app_url: "",
      public_base_url: "",
      default_request_timeout_seconds: 30,
      default_retry_count: 0,
      default_max_body_bytes: 1_000_000,
      default_model_sync_mode: "merge",
      default_virtual_key_expiration_days: undefined,
      virtual_key_prefix: "bab",
      allow_secret_copy: true,
    },
  });
  const modelSyncMode = useWatch({ control: form.control, name: "default_model_sync_mode" });
  const allowSecretCopy = useWatch({ control: form.control, name: "allow_secret_copy" });
  const updateSettings = useUpdateSettingsApiV1SettingsPatch({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          await queryClient.invalidateQueries();
          toast.success("Settings saved.");
        }
      },
      onError: () => toast.error("Settings could not be saved."),
    },
  });
  const uploadLogo = useUploadOrganizationLogoApiV1SettingsOrganizationLogoPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 200) {
          await queryClient.invalidateQueries();
          toast.success("Organization logo updated.");
        }
      },
      onError: () => toast.error("Logo could not be uploaded."),
    },
  });
  useEffect(() => {
    if (!settings) return;
    form.reset({
      organization_name: settings.organization_name,
      public_app_url: settings.public_app_url ?? "",
      public_base_url: settings.public_base_url ?? "",
      default_request_timeout_seconds: settings.default_request_timeout_seconds,
      default_retry_count: settings.default_retry_count,
      default_max_body_bytes: settings.default_max_body_bytes,
      default_model_sync_mode: toSyncMode(settings.default_model_sync_mode),
      default_virtual_key_expiration_days:
        settings.default_virtual_key_expiration_days ?? undefined,
      virtual_key_prefix: settings.virtual_key_prefix,
      allow_secret_copy: settings.allow_secret_copy,
    });
  }, [form, settings]);

  const submit = form.handleSubmit((values) => {
    if (!canManageSettings) return;
    const payload: UpdateOrganizationSettingsRequest = {
      ...values,
      public_app_url: values.public_app_url?.trim() ? values.public_app_url : null,
      public_base_url: values.public_base_url?.trim() ? values.public_base_url : null,
      default_virtual_key_expiration_days: values.default_virtual_key_expiration_days ?? null,
    };
    updateSettings.mutate({ data: payload });
  });
  const logoUrl = settings?.organization_logo_url
    ? resolveAssetUrl(settings.organization_logo_url)
    : null;
  const handleLogoChange = (file: File | undefined) => {
    if (!file) return;
    uploadLogo.mutate({ data: { file } });
    if (logoInputRef.current) {
      logoInputRef.current.value = "";
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Organization identity, gateway defaults, and security defaults."
        actions={
          canManageSettings ? (
            <Button
              type="submit"
              form="settings-form"
              disabled={updateSettings.isPending || settingsQuery.isPending}
            >
              <Save data-icon="inline-start" />
              {updateSettings.isPending ? "Saving..." : "Save settings"}
            </Button>
          ) : null
        }
      />
      {settingsQuery.isPending ? (
        <p className="text-sm text-muted-foreground">Loading settings...</p>
      ) : !settings ? (
        <EmptyState
          icon={Settings}
          title="Settings unavailable"
          description="The organization settings record could not be loaded."
        />
      ) : (
        <form id="settings-form" className="grid gap-4 xl:grid-cols-2" onSubmit={submit}>
          <Card>
            <CardHeader>
              <CardTitle>Organization</CardTitle>
              <CardDescription>Display identity for the current organization.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="flex items-center gap-4 rounded-md border p-3">
                <div className="flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-full border bg-muted">
                  {logoUrl ? (
                    <img src={logoUrl} alt="" className="size-full object-cover" />
                  ) : (
                    <ImageIcon className="size-5 text-muted-foreground" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">Organization logo</p>
                  <p className="text-xs text-muted-foreground">
                    Optional PNG, JPEG, or WebP image shown in the app header.
                  </p>
                </div>
                <input
                  ref={logoInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(event) => handleLogoChange(event.target.files?.[0])}
                />
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => logoInputRef.current?.click()}
                  disabled={uploadLogo.isPending || !canManageSettings}
                >
                  <Upload data-icon="inline-start" />
                  {uploadLogo.isPending ? "Uploading..." : "Upload"}
                </Button>
              </div>
              <Field label="Organization name" htmlFor="settings-org-name">
                <Input
                  id="settings-org-name"
                  disabled={!canManageSettings}
                  {...form.register("organization_name")}
                />
              </Field>
              <Field label="Public app URL" htmlFor="settings-public-app-url">
                <Input
                  id="settings-public-app-url"
                  placeholder="https://admin.example.com"
                  disabled={!canManageSettings}
                  {...form.register("public_app_url")}
                />
                <p className="text-xs text-muted-foreground">
                  App/admin console origin used for invite links.
                </p>
              </Field>
              <Field label="Public gateway URL" htmlFor="settings-public-url">
                <Input
                  id="settings-public-url"
                  placeholder="https://gateway.example.com"
                  disabled={!canManageSettings}
                  {...form.register("public_base_url")}
                />
                <p className="text-xs text-muted-foreground">
                  API/gateway origin used for docs and SDK examples.
                </p>
              </Field>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Gateway defaults</CardTitle>
              <CardDescription>
                Defaults used unless a provider or policy overrides them.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <NumberField
                label="Request timeout (seconds)"
                name="default_request_timeout_seconds"
                form={form}
                disabled={!canManageSettings}
              />
              <NumberField
                label="Retry count"
                name="default_retry_count"
                form={form}
                disabled={!canManageSettings}
              />
              <NumberField
                label="Max body bytes"
                name="default_max_body_bytes"
                form={form}
                disabled={!canManageSettings}
              />
              <Field label="Model sync mode">
                <Select
                  value={modelSyncMode}
                  disabled={!canManageSettings}
                  onValueChange={(value) =>
                    form.setValue(
                      "default_model_sync_mode",
                      value as SettingsValues["default_model_sync_mode"],
                      {
                        shouldDirty: true,
                      },
                    )
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="merge">Merge</SelectItem>
                    <SelectItem value="replace">Replace</SelectItem>
                    <SelectItem value="disabled">Disabled</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Stored organization default for provider model sync flows. Provider sync remains
                  manually triggered from each provider.
                </p>
              </Field>
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="text-sm font-medium">Usage retention</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {settings.usage_retention_days == null
                    ? "Retain usage records indefinitely. No retention deletion job is configured."
                    : `Retention intent is ${settings.usage_retention_days.toLocaleString()} days. No deletion job is configured.`}
                </div>
              </div>
              <div className="rounded-md border bg-muted/20 p-3">
                <div className="text-sm font-medium">Activity retention</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  {settings.activity_retention_days == null
                    ? "Retain activity events indefinitely. No retention deletion job is configured."
                    : `Retention intent is ${settings.activity_retention_days.toLocaleString()} days. No deletion job is configured.`}
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle>Virtual key defaults</CardTitle>
              <CardDescription>Defaults for newly issued client-facing keys.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-2">
              <Field label="Key prefix" htmlFor="settings-key-prefix">
                <Input
                  id="settings-key-prefix"
                  disabled={!canManageSettings}
                  {...form.register("virtual_key_prefix")}
                />
              </Field>
              <NumberField
                label="Default expiration days"
                name="default_virtual_key_expiration_days"
                form={form}
                disabled={!canManageSettings}
                placeholder="No default"
              />
              <div className="flex items-center justify-between gap-4 rounded-md border p-3 md:col-span-2">
                <div>
                  <Label htmlFor="settings-secret-copy">Return plaintext key once</Label>
                  <p className="mt-1 text-xs text-muted-foreground">
                    When off, newly created virtual keys are stored and usable but never returned to
                    the UI.
                  </p>
                </div>
                <Switch
                  id="settings-secret-copy"
                  checked={allowSecretCopy}
                  disabled={!canManageSettings}
                  onCheckedChange={(checked) =>
                    form.setValue("allow_secret_copy", checked, { shouldDirty: true })
                  }
                />
              </div>
            </CardContent>
          </Card>
        </form>
      )}
    </div>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}

function NumberField({
  label,
  name,
  form,
  placeholder,
  disabled,
}: {
  label: string;
  name:
    | "default_request_timeout_seconds"
    | "default_retry_count"
    | "default_max_body_bytes"
    | "default_virtual_key_expiration_days";
  form: ReturnType<typeof useForm<SettingsInput, unknown, SettingsValues>>;
  placeholder?: string;
  disabled?: boolean;
}) {
  return (
    <Field label={label} htmlFor={`settings-${name}`}>
      <Input
        id={`settings-${name}`}
        type="number"
        placeholder={placeholder}
        disabled={disabled}
        {...form.register(name)}
      />
    </Field>
  );
}

function optionalNumber(value: unknown) {
  return value === "" || value === null || value === undefined ? undefined : Number(value);
}

function toSyncMode(value: string): SettingsValues["default_model_sync_mode"] {
  if (value === "replace" || value === "disabled") return value;
  return "merge";
}

function resolveAssetUrl(url: string) {
  if (/^https?:\/\//i.test(url)) return url;
  const apiBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return apiBaseUrl ? new URL(url, apiBaseUrl).toString() : url;
}

function isAbsoluteHttpUrl(value: string) {
  try {
    const parsed = new URL(value);
    return (
      (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      !parsed.username &&
      !parsed.password &&
      parsed.pathname === "/" &&
      !parsed.search &&
      !parsed.hash
    );
  } catch {
    return false;
  }
}

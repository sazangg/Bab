import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { Check, Copy, KeyRound, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import {
  useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost,
  useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet,
  useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
} from "@/shared/api/generated/projects/projects";
import { useGetSettingsApiV1SettingsGet } from "@/shared/api/generated/settings/settings";
import type {
  CreatedVirtualKeyResponse,
  ProjectResponse,
  VirtualKeyResponse,
} from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { EffectiveAccessSummaryCard } from "@/features/projects/components/EffectiveAccessSummaryCard";

const STALE_KEY_DAYS = 30;

const keySchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
});

type KeyValues = z.infer<typeof keySchema>;

export function ProjectKeysSection({
  projectId,
  project,
  teamName,
  keys,
  isLoading,
  onView,
  canManage,
}: {
  projectId: string;
  project: ProjectResponse;
  teamName?: string;
  keys: VirtualKeyResponse[];
  isLoading: boolean;
  onView: (keyId: string) => void;
  canManage: boolean;
}) {
  const queryClient = useQueryClient();
  const [createOpen, setCreateOpen] = useState(false);
  const [createdKey, setCreatedKey] = useState<CreatedVirtualKeyResponse | null>(null);
  const [revokeId, setRevokeId] = useState<string | null>(null);
  const [revokeReason, setRevokeReason] = useState("");
  const [copied, setCopied] = useState(false);

  const form = useForm<KeyValues>({
    resolver: zodResolver(keySchema),
    defaultValues: {
      name: "",
      expires_at: "",
    },
  });
  const preflightQuery = useGetProjectEffectiveAccessApiV1ProjectsProjectIdEffectiveAccessGet(
    projectId,
    { query: { enabled: canManage && Boolean(projectId) } },
  );
  const preflight = preflightQuery.data?.status === 200 ? preflightQuery.data.data : undefined;
  const settingsQuery = useGetSettingsApiV1SettingsGet();
  const settings = settingsQuery.data?.status === 200 ? settingsQuery.data.data : undefined;
  const gatewayBaseUrl = resolveGatewayBaseUrl(settings?.public_base_url);
  const canCreateKey = Boolean(project.is_active && preflight?.is_usable);
  const revokeImpactQuery = useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet(
    projectId,
    revokeId ?? "",
    { query: { enabled: Boolean(revokeId) } },
  );
  const revokeImpact =
    revokeImpactQuery.data?.status === 200 ? revokeImpactQuery.data.data : null;

  const createMutation = useCreateVirtualKeyApiV1ProjectsProjectIdKeysPost({
    mutation: {
      onSuccess: async (response) => {
        if (response.status === 201) {
          setCreatedKey(response.data);
          form.reset({
            name: "",
            expires_at: "",
          });
          setCreateOpen(false);
          await queryClient.invalidateQueries();
        }
      },
      onError: (error) => {
        toast.error(getMutationDetail(error, "Virtual key could not be created."));
      },
    },
  });
  const revokeMutation = useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete({
    mutation: {
      onSuccess: async () => {
        setRevokeId(null);
        setRevokeReason("");
        await queryClient.invalidateQueries();
      },
    },
  });

  const submit = (values: KeyValues) =>
    createMutation.mutate({
      projectId,
      data: {
        name: values.name,
        expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
      },
    });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>Virtual keys</CardTitle>
          <CardDescription>
            Each key uses the access and limit policies assigned to its project, team, and
            organization. Key-specific access is managed through virtual key policy assignments.
          </CardDescription>
          {canManage ? (
            <CardAction>
              <Sheet open={createOpen} onOpenChange={setCreateOpen}>
                <SheetTrigger asChild>
                  <Button size="sm" disabled={!project.is_active}>
                    <Plus />
                    New key
                  </Button>
                </SheetTrigger>
                <SheetContent>
                  <SheetHeader>
                    <SheetTitle>New virtual key</SheetTitle>
                    <SheetDescription>
                      Keys inherit the active access and limit policies assigned upstream.
                    </SheetDescription>
                  </SheetHeader>
                  <div className="px-6 pt-5">
                    <EffectiveAccessSummaryCard
                      summary={preflight}
                      isLoading={preflightQuery.isPending}
                    />
                    {preflight && !preflight.is_usable ? (
                      <p className="mt-3 text-sm text-muted-foreground">
                        Configure an active access policy and routable provider/model before
                        creating a key.
                      </p>
                    ) : null}
                  </div>
                  <form
                    className="grid gap-4 overflow-y-auto px-6 py-5"
                    onSubmit={form.handleSubmit(submit)}
                  >
                    <div className="space-y-1.5">
                      <Label htmlFor="key-name">Label</Label>
                      <Input id="key-name" autoFocus {...form.register("name")} />
                      {form.formState.errors.name ? (
                        <p className="text-xs text-destructive">
                          {form.formState.errors.name.message}
                        </p>
                      ) : null}
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor="key-expires">Expires at</Label>
                      <Input
                        id="key-expires"
                        type="datetime-local"
                        {...form.register("expires_at")}
                      />
                      <p className="text-xs text-muted-foreground">
                        Optional. Blank uses the organization default if configured.
                      </p>
                    </div>
                  </form>
                  <SheetFooter>
                    <Button
                      type="submit"
                      disabled={createMutation.isPending || !canCreateKey}
                      onClick={form.handleSubmit(submit)}
                    >
                      {createMutation.isPending ? "Creating..." : "Create key"}
                    </Button>
                    <SheetClose asChild>
                      <Button variant="outline">Cancel</Button>
                    </SheetClose>
                  </SheetFooter>
                </SheetContent>
              </Sheet>
            </CardAction>
          ) : null}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Loading keys...</p>
          ) : keys.length === 0 ? (
            <EmptyState
              icon={KeyRound}
              title="No virtual keys yet"
              description="Create a key to issue this project's first credential."
            />
          ) : (
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Label</TableHead>
                    <TableHead>Prefix</TableHead>
                    <TableHead>Policy</TableHead>
                    <TableHead>Usage</TableHead>
                    <TableHead>Expires</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="w-[1%]" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {keys.map((key) => (
                    <TableRow
                      key={key.id}
                      className="cursor-pointer"
                      onClick={() => onView(key.id)}
                    >
                      <TableCell className="font-medium">{key.name}</TableCell>
                      <TableCell className="font-mono text-xs">{key.key_prefix}</TableCell>
                      <TableCell className="text-muted-foreground">
                        <div className="flex flex-col gap-1">
                          <span>Policy governed</span>
                          <span className="text-xs">Access and limits resolve at request time</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        <KeyUsageInline lastUsedAt={key.last_used_at} />
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {key.expires_at ? new Date(key.expires_at).toLocaleDateString() : "Never"}
                      </TableCell>
                      <TableCell>
                        <KeyStatusBadge virtualKey={key} />
                      </TableCell>
                      <TableCell
                        className="text-right"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {canManage && !key.revoked_at ? (
                          <Button variant="ghost" size="sm" onClick={() => setRevokeId(key.id)}>
                            Revoke
                          </Button>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog
        open={Boolean(createdKey)}
        onOpenChange={(open) => {
          if (!open) {
            setCreatedKey(null);
            setCopied(false);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Key created</DialogTitle>
            <DialogDescription>
              {createdKey?.key
                ? "Copy the key now. It cannot be displayed again after this dialog closes."
                : "Secret copy is disabled in settings, so the plaintext key was not returned."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm md:grid-cols-2">
            <Fact label="Project" value={project.name} />
            <Fact label="Team" value={teamName ?? "Organization owned"} />
            <Fact label="Gateway base URL" value={gatewayBaseUrl} />
            <Fact
              label="Effective routes"
              value={
                preflight?.routes.length
                  ? preflight.routes
                      .slice(0, 2)
                      .map((route) => route.alias ?? route.provider_model)
                      .join(", ")
                  : "No route summary"
              }
            />
            <Fact
              label="Expires"
              value={
                createdKey?.expires_at ? new Date(createdKey.expires_at).toLocaleString() : "Never"
              }
            />
          </div>
          {createdKey?.key ? (
            <div className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
              <code className="min-w-0 flex-1 overflow-auto text-xs">{createdKey.key}</code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  navigator.clipboard.writeText(createdKey.key ?? "");
                  setCopied(true);
                }}
              >
                {copied ? <Check /> : <Copy />}
                {copied ? "Copied" : "Copy"}
              </Button>
            </div>
          ) : (
            <div className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
              Key prefix:{" "}
              <span className="font-mono text-foreground">{createdKey?.key_prefix}</span>
            </div>
          )}
          <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            Store this secret in your application secret manager. Bab keeps only a hash and will not
            show the plaintext key again.
          </div>
          {createdKey?.key ? (
            <pre className="overflow-auto rounded-md border bg-background p-3 text-xs">
              <code>
                {sampleCurl({
                  baseUrl: gatewayBaseUrl,
                  key: createdKey.key,
                  model:
                    preflight?.routes[0]?.alias ??
                    preflight?.routes[0]?.provider_model ??
                    "model-name",
                })}
              </code>
            </pre>
          ) : null}
          <DialogFooter>
            <DialogClose asChild>
              <Button>Done</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={Boolean(revokeId)}
        onOpenChange={(open) => {
          if (!open) {
            setRevokeId(null);
            setRevokeReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke this key?</DialogTitle>
            <DialogDescription>
              The key will stop authenticating immediately. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {revokeImpactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Checking impact...</p>
          ) : revokeImpact ? (
            <div className="space-y-3">
              <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm md:grid-cols-3">
                <Fact
                  label="Last used"
                  value={
                    revokeImpact.last_used_at
                      ? new Date(revokeImpact.last_used_at).toLocaleString()
                      : "Never"
                  }
                />
                <Fact
                  label={`${revokeImpact.recent_usage_window_days}d requests`}
                  value={(revokeImpact.recent_request_count ?? 0).toLocaleString()}
                />
                <Fact label="Estimated spend" value={formatCents(revokeImpact.recent_cost_cents)} />
              </div>
              {revokeImpact.already_unusable_reason ? (
                <p className="text-sm text-muted-foreground">
                  This key is already unusable: {revokeImpact.already_unusable_reason}
                </p>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Impact could not be loaded. You can retry by reopening this dialog.
            </p>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="project-key-revoke-reason">Reason</Label>
            <Textarea
              id="project-key-revoke-reason"
              value={revokeReason}
              maxLength={500}
              onChange={(event) => setRevokeReason(event.target.value)}
              placeholder="Why is this key being revoked?"
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={revokeMutation.isPending || !revokeReason.trim()}
              onClick={() =>
                revokeId &&
                revokeMutation.mutate({
                  projectId,
                  keyId: revokeId,
                  data: { reason: revokeReason.trim() },
                })
              }
            >
              {revokeMutation.isPending ? "Revoking..." : "Revoke key"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function KeyStatusBadge({ virtualKey }: { virtualKey: VirtualKeyResponse }) {
  return (
    <StatusBadge variant={keyStatusVariant(virtualKey.status)}>
      {virtualKey.status.replaceAll("_", " ")}
    </StatusBadge>
  );
}

function keyStatusVariant(status: string) {
  if (status === "active" || status === "unused") return "active";
  if (status === "revoked") return "revoked";
  if (status === "expired" || status === "expiring_soon") return "expired";
  return "inactive";
}

function KeyUsageInline({
  lastUsedAt,
}: {
  lastUsedAt: string | null | undefined;
}) {
  return (
    <div className="flex flex-col gap-1 text-xs">
      <span className="font-medium text-foreground">{lastUsedAt ? "Observed" : "No usage"}</span>
      <span className="text-muted-foreground">{keyUsageLabel(lastUsedAt)}</span>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

function formatCents(value: number | null | undefined) {
  return `$${((value ?? 0) / 100).toFixed(2)}`;
}

function keyUsageLabel(lastUsedAt: string | null | undefined) {
  if (!lastUsedAt) return "Never used";
  const ageMs = Date.now() - new Date(lastUsedAt).getTime();
  const ageDays = Math.floor(ageMs / 86_400_000);
  if (ageDays >= STALE_KEY_DAYS) return `Unused for ${ageDays}d`;
  return `Last used ${ageDays === 0 ? "today" : `${ageDays}d ago`}`;
}

function resolveGatewayBaseUrl(publicBaseUrl?: string | null) {
  if (publicBaseUrl?.trim()) return publicBaseUrl.replace(/\/+$/, "");
  const envBaseUrl = import.meta.env.VITE_BAB_API_URL as string | undefined;
  return envBaseUrl?.replace(/\/+$/, "") ?? "http://localhost:8000";
}

function sampleCurl({ baseUrl, key, model }: { baseUrl: string; key: string; model: string }) {
  return `curl ${baseUrl}/v1/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${model}",
    "messages": [{"role": "user", "content": "Reply with pong"}],
    "max_completion_tokens": 32
  }'`;
}

function getMutationDetail(error: unknown, fallback: string) {
  if (!isAxiosError(error)) return fallback;
  const detail = error.response?.data?.detail;
  return typeof detail === "string" && detail.length > 0 ? detail : fallback;
}

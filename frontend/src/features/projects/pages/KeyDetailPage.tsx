import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import { ArrowLeft, Gauge, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import {
  useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet,
  useGetVirtualKeyEffectiveAccessApiV1ProjectsProjectIdKeysKeyIdEffectiveAccessGet,
  useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet,
  useGetVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet,
  useListProjectsApiV1ProjectsGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
  useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListMembersApiV1AuthMembersGet, useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
} from "@/components/ui/sheet";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import type { MemberResponse, UsageBreakdownRow, UsageRecentError } from "@/shared/api/generated/schemas";
import { hasPermission, isProjectAdmin, isTeamAdmin } from "@/features/auth/lib/permissions";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";
import { RecentGuardrailEventsCard } from "@/features/guardrails/components/RecentGuardrailEventsCard";
import { PolicyScopeSection } from "@/features/policies/components/PolicyScopeSection";
import { EffectiveAccessSummaryCard } from "@/features/projects/components/EffectiveAccessSummaryCard";

const STALE_KEY_DAYS = 30;

const editSchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
});

type EditValues = z.infer<typeof editSchema>;

export function KeyDetailPage() {
  const { projectId = "", keyId = "" } = useParams<{ projectId: string; keyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [revokeReason, setRevokeReason] = useState("");

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const project =
    projectsQuery.data?.status === 200
      ? projectsQuery.data.data.find((p) => p.id === projectId)
      : undefined;
  const currentUserQuery = useMeApiV1AuthMeGet();
  const orgMembersQuery = useListMembersApiV1AuthMembersGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const keyQuery = useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet(projectId, keyId, {
    query: { enabled: Boolean(projectId && keyId) },
  });
  const usageQuery = useGetVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet(
    projectId,
    keyId,
    { query: { enabled: Boolean(projectId && keyId) } },
  );
  const accessQuery =
    useGetVirtualKeyEffectiveAccessApiV1ProjectsProjectIdKeysKeyIdEffectiveAccessGet(
      projectId,
      keyId,
      { query: { enabled: Boolean(projectId && keyId) } },
    );
  const revokeImpactQuery =
    useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet(
      projectId,
      keyId,
      { query: { enabled: revokeOpen && Boolean(projectId && keyId) } },
    );

  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const orgMembers = orgMembersQuery.data?.status === 200 ? orgMembersQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const key = keyQuery.data?.status === 200 ? keyQuery.data.data : undefined;
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : undefined;
  const revokeImpact =
    revokeImpactQuery.data?.status === 200 ? revokeImpactQuery.data.data : null;
  const canManageKey = project
    ? hasPermission(currentUser, "keys.manage") ||
      isTeamAdmin(currentUser, project.team_id) ||
      isProjectAdmin(currentUser, project.id)
    : false;
  const team = project ? teams.find((item) => item.id === project.team_id) : undefined;
  const creator = key?.created_by
    ? orgMembers.find((member) => member.user_id === key.created_by)
    : undefined;
  const revoker = key?.revoked_by
    ? orgMembers.find((member) => member.user_id === key.revoked_by)
    : undefined;

  const updateMutation = useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch({
    mutation: {
      onSuccess: async () => {
        setEditOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });
  const revokeMutation = useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete({
    mutation: {
      onSuccess: async () => {
        setRevokeOpen(false);
        setRevokeReason("");
        await queryClient.invalidateQueries();
        navigate(`/projects/${projectId}`);
      },
    },
  });

  const form = useForm<EditValues>({
    resolver: zodResolver(editSchema),
    defaultValues: {
      name: "",
      expires_at: "",
    },
  });

  useEffect(() => {
    if (key && editOpen) {
      form.reset({
        name: key.name,
        expires_at: key.expires_at ? toLocalInput(key.expires_at) : "",
      });
    }
  }, [editOpen, key, form]);

  if (keyQuery.isPending || projectsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading key...</p>;
  }
  if (isAxiosError(keyQuery.error) && keyQuery.error.response?.status === 403) {
    return <ForbiddenPage />;
  }

  if (!key || !project) {
    return (
      <PageHeader
        title="Key not found"
        description="The key may have been removed."
        actions={
          <Button asChild variant="outline">
            <Link to={projectId ? `/projects/${projectId}` : "/projects"}>
              <ArrowLeft />
              Back
            </Link>
          </Button>
        }
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={key.name}
        description={`Project: ${project.name}`}
        actions={
          canManageKey ? (
            <div className="flex items-center gap-2">
              <Button variant="outline" onClick={() => setEditOpen(true)}>
                <Pencil />
                Edit key
              </Button>
              {!key.revoked_at ? (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="outline" size="icon" aria-label="Key actions">
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setRevokeOpen(true)} variant="destructive">
                      <Trash2 className="mr-2 size-4" />
                      Revoke key
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : null}
            </div>
          ) : null
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Key summary</CardTitle>
          <CardDescription className="font-mono text-xs">{key.key_prefix}</CardDescription>
          <CardAction>
            <StatusBadge variant={keyStatusVariant(key.status)}>
              {key.status.replaceAll("_", " ")}
            </StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact
            label="Expires"
            value={key.expires_at ? new Date(key.expires_at).toLocaleString() : "Never"}
          />
          <Fact label="Policy" value="Resolved at request time" />
          <Fact label="Last used" value={keyUsageLabel(key.last_used_at)} />
          <Fact label="Created" value={new Date(key.created_at).toLocaleString()} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ownership</CardTitle>
          <CardDescription>Application ownership and lifecycle actors for this key.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact label="Project" value={project.name} />
          <Fact label="Team" value={team?.name ?? "Unknown"} />
          <Fact label="Created by" value={formatMember(creator, key.created_by)} />
          <Fact label="Revoked by" value={key.revoked_by ? formatMember(revoker, key.revoked_by) : "Not revoked"} />
        </CardContent>
      </Card>

      <EffectiveAccessSummaryCard
        summary={accessQuery.data?.status === 200 ? accessQuery.data.data : undefined}
        isLoading={accessQuery.isPending}
      />

      <Card>
        <CardHeader>
          <CardTitle>Policy scope</CardTitle>
          <CardDescription>
            Keys inherit access and limit policies from the organization, team, and project. The key
            can define narrower policies through virtual key policy assignments.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <Fact label="Access" value="Policy governed" />
          <Fact label="Limits" value="Policy governed" />
        </CardContent>
      </Card>

      <PolicyScopeSection
        target={{ type: "virtual_key", projectId: project.id, virtualKeyId: key.id }}
        canManage={canManageKey}
      />

      <KeyUsageCard usage={usage} />
      <UsageRecordsDrilldown
        title="Key usage records"
        filters={{ project_id: project.id, virtual_key_id: key.id }}
      />
      <RecentGuardrailEventsCard
        title="Key guardrail events"
        filters={{ virtual_key_id: key.id }}
      />

      {canManageKey ? (
        <Sheet open={editOpen} onOpenChange={setEditOpen}>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>Edit key</SheetTitle>
              <SheetDescription>
                Rename the key or update its expiration. Access stays policy-governed.
              </SheetDescription>
            </SheetHeader>
            <form
              id="edit-key-form"
              className="grid gap-4 overflow-y-auto px-6 py-5"
              onSubmit={form.handleSubmit((values) =>
                updateMutation.mutate({
                  projectId,
                  keyId,
                  data: {
                    name: values.name,
                    expires_at: values.expires_at
                      ? new Date(values.expires_at).toISOString()
                      : null,
                  },
                }),
              )}
            >
              <div className="space-y-1.5">
                <Label htmlFor="edit-key-name">Label</Label>
                <Input id="edit-key-name" autoFocus {...form.register("name")} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="edit-key-expires">Expires at</Label>
                <Input
                  id="edit-key-expires"
                  type="datetime-local"
                  {...form.register("expires_at")}
                />
              </div>
            </form>
            <SheetFooter>
              <Button type="submit" form="edit-key-form" disabled={updateMutation.isPending}>
                {updateMutation.isPending ? "Saving..." : "Save changes"}
              </Button>
              <SheetClose asChild>
                <Button variant="outline">Cancel</Button>
              </SheetClose>
            </SheetFooter>
          </SheetContent>
        </Sheet>
      ) : null}

      {canManageKey ? (
        <Dialog open={revokeOpen} onOpenChange={setRevokeOpen}>
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
                  <Fact
                    label="Estimated spend"
                    value={formatCents(revokeImpact.recent_cost_cents)}
                  />
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
              <Label htmlFor="revoke-key-reason">Reason</Label>
              <Textarea
                id="revoke-key-reason"
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
                  revokeMutation.mutate({
                    projectId,
                    keyId,
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
      ) : null}
    </div>
  );
}

function keyStatusVariant(status: string) {
  if (status === "active" || status === "unused") return "active";
  if (status === "revoked") return "revoked";
  if (status === "expired" || status === "expiring_soon") return "expired";
  return "inactive";
}

function KeyUsageCard({
  usage,
}: {
  usage:
    | {
        totals: {
          requests?: number;
          total_tokens?: number;
          cost_cents?: number;
          failed_requests?: number;
          average_latency_ms?: number | null;
          last_request_at?: string | null;
        };
        by_provider: UsageBreakdownRow[];
        by_model: UsageBreakdownRow[];
        by_pool: UsageBreakdownRow[];
        by_access_policy: UsageBreakdownRow[];
        recent_errors?: UsageRecentError[];
      }
    | undefined;
}) {
  const totals = usage?.totals;
  const requests = totals?.requests ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Usage</CardTitle>
        <CardDescription>
          Key-scoped request, spend, routing, and error attribution.
        </CardDescription>
        <CardAction>
          <StatusBadge variant={requests > 0 ? "active" : "muted"}>
            {requests > 0 ? "Observed" : "No usage"}
          </StatusBadge>
        </CardAction>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-5">
          <Fact label="Requests" value={requests.toLocaleString()} />
          <Fact label="Tokens" value={(totals?.total_tokens ?? 0).toLocaleString()} />
          <Fact label="Spend" value={formatCents(totals?.cost_cents ?? 0)} />
          <Fact label="Errors" value={(totals?.failed_requests ?? 0).toLocaleString()} />
          <Fact
            label="Last request"
            value={totals?.last_request_at ? new Date(totals.last_request_at).toLocaleString() : "-"}
          />
        </div>
        <RecentErrors rows={usage?.recent_errors ?? []} />
        {requests === 0 ? (
          <div className="rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <Gauge className="size-4" />
              No proxy usage has been recorded for this key yet.
            </div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <BreakdownList title="Providers" rows={usage?.by_provider ?? []} />
            <BreakdownList title="Models" rows={usage?.by_model ?? []} />
            <BreakdownList title="Pools" rows={usage?.by_pool ?? []} />
            <BreakdownList title="Access policies" rows={usage?.by_access_policy ?? []} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function RecentErrors({ rows }: { rows: UsageRecentError[] }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 text-xs font-medium text-muted-foreground">Recent errors</div>
      {rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">No recent errors for this key.</p>
      ) : (
        <div className="space-y-1.5">
          {rows.map((row) => (
            <div key={row.id} className="flex items-center justify-between gap-3 text-xs">
              <span className="min-w-0 truncate">
                {row.error_code ?? `HTTP ${row.http_status}`} · {row.requested_model}
              </span>
              <span className="shrink-0 text-muted-foreground">
                {new Date(row.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function BreakdownList({ title, rows }: { title: string; rows: UsageBreakdownRow[] }) {
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 text-xs font-medium text-muted-foreground">{title}</div>
      <div className="space-y-1.5">
        {rows.slice(0, 5).map((row) => (
          <div key={row.id} className="flex items-center justify-between gap-3 text-xs">
            <span className="min-w-0 truncate">{row.label}</span>
            <span className="shrink-0 text-muted-foreground">
              {(row.requests ?? 0).toLocaleString()} req ·{" "}
              {(row.total_tokens ?? 0).toLocaleString()} tok
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

function toLocalInput(iso: string) {
  const d = new Date(iso);
  const offset = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 16);
}

function formatCents(value: number | null | undefined) {
  return value == null ? "$0" : `$${(value / 100).toLocaleString()}`;
}

function keyUsageLabel(lastUsedAt: string | null | undefined) {
  if (!lastUsedAt) return "Never used";
  const ageMs = Date.now() - new Date(lastUsedAt).getTime();
  const ageDays = Math.floor(ageMs / 86_400_000);
  if (ageDays >= STALE_KEY_DAYS) return `Unused for ${ageDays}d`;
  return `Last used ${ageDays === 0 ? "today" : `${ageDays}d ago`}`;
}

function formatMember(member: MemberResponse | undefined, fallbackId: string | null | undefined) {
  if (member?.name) return member.name;
  if (member?.email) return member.email;
  return fallbackId ? fallbackId.slice(0, 8) : "Unknown";
}

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
  useGetVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet,
  useListProjectsApiV1ProjectsGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
  useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";
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
import type { UsageBreakdownRow } from "@/shared/api/generated/schemas";
import { hasPermission, isTeamAdmin } from "@/features/auth/lib/permissions";
import { ForbiddenPage } from "@/features/auth/components/ProtectedRoute";
import { UsageRecordsDrilldown } from "@/features/usage/components/UsageRecordsDrilldown";
import { RecentGuardrailEventsCard } from "@/features/guardrails/components/RecentGuardrailEventsCard";

const editSchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
  allowed_models: z.string().optional(),
});

type EditValues = z.infer<typeof editSchema>;

export function KeyDetailPage() {
  const { projectId = "", keyId = "" } = useParams<{ projectId: string; keyId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);

  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const project =
    projectsQuery.data?.status === 200
      ? projectsQuery.data.data.find((p) => p.id === projectId)
      : undefined;
  const currentUserQuery = useMeApiV1AuthMeGet();
  const keyQuery = useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet(projectId, keyId, {
    query: { enabled: Boolean(projectId && keyId) },
  });
  const usageQuery = useGetVirtualKeyUsageApiV1ProjectsProjectIdKeysKeyIdUsageGet(
    projectId,
    keyId,
    { query: { enabled: Boolean(projectId && keyId) } },
  );

  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const key = keyQuery.data?.status === 200 ? keyQuery.data.data : undefined;
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : undefined;
  const canManageKey = project
    ? hasPermission(currentUser, "keys.manage") || isTeamAdmin(currentUser, project.team_id)
    : false;

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
      allowed_models: "",
    },
  });

  useEffect(() => {
    if (key && editOpen) {
      form.reset({
        name: key.name,
        expires_at: key.expires_at ? toLocalInput(key.expires_at) : "",
        allowed_models: key.allowed_models?.join(", ") ?? "",
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

  const status = key.revoked_at
    ? ("revoked" as const)
    : key.expires_at && new Date(key.expires_at) < new Date()
      ? ("expired" as const)
      : ("active" as const);

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
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="icon" aria-label="Key actions">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onSelect={() => setRevokeOpen(true)}
                    disabled={Boolean(key.revoked_at)}
                    variant="destructive"
                  >
                    <Trash2 className="mr-2 size-4" />
                    Revoke key
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : null
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Key summary</CardTitle>
          <CardDescription className="font-mono text-xs">{key.key_prefix}</CardDescription>
          <CardAction>
            <StatusBadge variant={status}>{status[0].toUpperCase() + status.slice(1)}</StatusBadge>
          </CardAction>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-4">
          <Fact
            label="Expires"
            value={key.expires_at ? new Date(key.expires_at).toLocaleString() : "Never"}
          />
          <Fact label="Policy" value="Resolved at request time" />
          <Fact label="Allowed models" value={formatModels(key.allowed_models)} />
          <Fact label="Created" value={new Date(key.created_at).toLocaleString()} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Policy scope</CardTitle>
          <CardDescription>
            Keys inherit access and limit policies from the organization, team, and project. The
            key can only narrow model access.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-3">
          <Fact label="Access" value="Policy governed" />
          <Fact label="Limits" value="Policy governed" />
          <Fact label="Key model subset" value={formatModels(key.allowed_models)} />
        </CardContent>
      </Card>

      <KeyUsageCard usage={usage} />
      <UsageRecordsDrilldown
        title="Key usage records"
        filters={{ project_id: project.id, virtual_key_id: key.id }}
      />
      <RecentGuardrailEventsCard title="Key guardrail events" filters={{ virtual_key_id: key.id }} />

      {canManageKey ? (
        <Sheet open={editOpen} onOpenChange={setEditOpen}>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>Edit key</SheetTitle>
              <SheetDescription>
                A key can narrow access by allowed model names.
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
                    allowed_models: parseModels(values.allowed_models),
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
              <div className="space-y-1.5">
                <Label htmlFor="edit-key-models">Allowed models</Label>
                <Input
                  id="edit-key-models"
                  placeholder="gpt-4o-mini"
                  {...form.register("allowed_models")}
                />
                <p className="text-xs text-muted-foreground">
                  Optional comma-separated subset of the models allowed by policies.
                </p>
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
            <DialogFooter>
              <Button
                variant="destructive"
                disabled={revokeMutation.isPending}
                onClick={() => revokeMutation.mutate({ projectId, keyId })}
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
        };
        by_provider: UsageBreakdownRow[];
        by_model: UsageBreakdownRow[];
        by_pool: UsageBreakdownRow[];
        by_access_policy: UsageBreakdownRow[];
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
            label="Latency"
            value={totals?.average_latency_ms == null ? "-" : `${totals.average_latency_ms}ms`}
          />
        </div>
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

function formatModels(models: string[] | null | undefined) {
  return models && models.length > 0 ? models.join(", ") : "All policy route models";
}

function toLocalInput(iso: string) {
  const d = new Date(iso);
  const offset = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - offset).toISOString().slice(0, 16);
}

function parseModels(value: string | undefined): string[] | null {
  const models = value
    ?.split(",")
    .map((model) => model.trim())
    .filter(Boolean);
  return models && models.length > 0 ? models : null;
}

function formatCents(value: number | null | undefined) {
  return value == null ? "$0" : `$${(value / 100).toLocaleString()}`;
}

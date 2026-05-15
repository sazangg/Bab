import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { useGetKeyUsageApiV1AnalyticsKeysVirtualKeyIdGet } from "@/shared/api/generated/analytics/analytics";
import {
  useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet,
  useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet,
  useListProjectsApiV1ProjectsGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
  useUpdateVirtualKeyApiV1ProjectsProjectIdKeysKeyIdPatch,
} from "@/shared/api/generated/projects/projects";
import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import type { VirtualKeyRestriction } from "@/shared/api/generated/schemas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PageHeader } from "@/shared/components/PageHeader";
import { HttpStatusBadge, StatusBadge } from "@/shared/components/StatusBadge";

const editSchema = z.object({
  name: z.string().min(1).max(255),
  expires_at: z.string().optional(),
  provider_id: z.string().optional(),
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
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const keyQuery = useGetVirtualKeyApiV1ProjectsProjectIdKeysKeyIdGet(projectId, keyId, {
    query: { enabled: Boolean(projectId && keyId) },
  });
  const allocationsQuery = useListProjectAllocationsApiV1ProjectsProjectIdAllocationsGet(
    projectId,
    { query: { enabled: Boolean(projectId) } },
  );
  const usageQuery = useGetKeyUsageApiV1AnalyticsKeysVirtualKeyIdGet(
    keyId,
    { days: 7, recent_limit: 20 },
    { query: { enabled: Boolean(keyId) } },
  );

  const project =
    projectsQuery.data?.status === 200
      ? projectsQuery.data.data.find((p) => p.id === projectId)
      : undefined;
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const key = keyQuery.data?.status === 200 ? keyQuery.data.data : undefined;
  const usage = usageQuery.data?.status === 200 ? usageQuery.data.data : null;
  const allocations = allocationsQuery.data?.status === 200 ? allocationsQuery.data.data : [];

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
    defaultValues: { name: "", expires_at: "", provider_id: "", allowed_models: "" },
  });
  const selectedProviderId = useWatch({ control: form.control, name: "provider_id" });

  useEffect(() => {
    if (key && editOpen) {
      const firstRestriction = key.restrictions?.[0];
      form.reset({
        name: key.name,
        expires_at: key.expires_at ? toLocalInput(key.expires_at) : "",
        provider_id: firstRestriction?.provider_id ?? "",
        allowed_models: firstRestriction?.allowed_models?.join(", ") ?? "",
      });
    }
  }, [editOpen, key, form]);

  if (keyQuery.isPending || projectsQuery.isPending) {
    return <p className="text-sm text-muted-foreground">Loading key...</p>;
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
    <>
      <PageHeader
        title={key.name}
        description={`Project: ${project.name}`}
        actions={
          <>
            <StatusBadge variant={status}>{status[0].toUpperCase() + status.slice(1)}</StatusBadge>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Key actions">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setEditOpen(true)}>
                  <Pencil className="mr-2 size-4" />
                  Edit key
                </DropdownMenuItem>
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
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <KeyMetric label="Prefix" value={key.key_prefix} mono />
        <KeyMetric
          label="Expires"
          value={key.expires_at ? new Date(key.expires_at).toLocaleString() : "Never"}
        />
        <KeyMetric label="Requests (7d)" value={usage?.totals.request_count ?? 0} />
        <KeyMetric label="Tokens (7d)" value={usage?.totals.total_tokens ?? 0} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Restrictions</CardTitle>
          <CardDescription>
            Active restrictions narrow this key below the project's access.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!key.restrictions || key.restrictions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No restrictions. Inherits all access from project: {accessSummary(allocations.length)}
              .
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead>Allowed models</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {key.restrictions.map((restriction: VirtualKeyRestriction) => (
                  <TableRow key={restriction.provider_id}>
                    <TableCell>
                      {providers.find((p) => p.id === restriction.provider_id)?.name ??
                        restriction.provider_id}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {restriction.allowed_models?.join(", ") ?? "All models"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Recent requests</CardTitle>
          <CardDescription>Last 20 calls made with this key.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Model</TableHead>
                <TableHead className="text-right">Tokens</TableHead>
                <TableHead className="text-right">Latency</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(usage?.recent_requests ?? []).map((req) => (
                <TableRow key={req.id}>
                  <TableCell className="text-muted-foreground tabular-nums">
                    {new Date(req.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <HttpStatusBadge status={req.http_status} />
                  </TableCell>
                  <TableCell className="font-mono text-xs">{req.requested_model}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {req.total_tokens ?? "—"}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{req.latency_ms} ms</TableCell>
                </TableRow>
              ))}
              {usage && usage.recent_requests.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    No requests with this key yet.
                  </TableCell>
                </TableRow>
              ) : null}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit key</DialogTitle>
            <DialogDescription>
              Restrictions can only narrow the project provider access.
            </DialogDescription>
          </DialogHeader>
          <form
            id="edit-key-form"
            className="grid gap-4"
            onSubmit={form.handleSubmit((values) =>
              updateMutation.mutate({
                projectId,
                keyId,
                data: {
                  name: values.name,
                  expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null,
                  restrictions: values.provider_id
                    ? [
                        {
                          provider_id: values.provider_id,
                          allowed_models: parseModels(values.allowed_models),
                        },
                      ]
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
              <Input id="edit-key-expires" type="datetime-local" {...form.register("expires_at")} />
            </div>
            <div className="space-y-1.5">
              <Label>Narrow to provider</Label>
              <Select
                value={selectedProviderId || "__all"}
                onValueChange={(value) =>
                  form.setValue("provider_id", value === "__all" ? "" : value)
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all">No restriction</SelectItem>
                  {allocations.map((allocation) => {
                    const provider = providers.find((p) => p.id === allocation.provider_id);
                    return (
                      <SelectItem key={allocation.provider_id} value={allocation.provider_id}>
                        {provider?.name ?? allocation.provider_id}
                      </SelectItem>
                    );
                  })}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="edit-key-models">Allowed models</Label>
              <Input
                id="edit-key-models"
                placeholder="gpt-4o-mini"
                {...form.register("allowed_models")}
              />
              <p className="text-xs text-muted-foreground">
                Comma-separated. Only used when a provider restriction is selected.
              </p>
            </div>
          </form>
          <DialogFooter>
            <Button type="submit" form="edit-key-form" disabled={updateMutation.isPending}>
              {updateMutation.isPending ? "Saving..." : "Save changes"}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
    </>
  );
}

function KeyMetric({
  label,
  value,
  mono,
}: {
  label: string;
  value: string | number;
  mono?: boolean;
}) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className={mono ? "font-mono text-base" : "text-2xl tabular-nums"}>
          {value}
        </CardTitle>
      </CardHeader>
    </Card>
  );
}

function accessSummary(count: number) {
  if (count === 0) return "no providers attached";
  return `${count} provider${count === 1 ? "" : "s"}`;
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

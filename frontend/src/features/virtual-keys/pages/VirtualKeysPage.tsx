import { useQueryClient } from "@tanstack/react-query";
import { KeyRound, Search, Trash2 } from "lucide-react";
import { useDeferredValue, useState } from "react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DataTable } from "@/components/ui/data-table";
import { Textarea } from "@/components/ui/textarea";
import { useIsMobile } from "@/hooks/use-mobile";
import {
  useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet,
  useListProjectsApiV1ProjectsGet,
  useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete,
} from "@/shared/api/generated/projects/projects";
import { useListTeamsApiV1TeamsGet } from "@/shared/api/generated/teams/teams";
import { useListVirtualKeyInventoryApiV1VirtualKeysGet } from "@/shared/api/generated/virtual-keys/virtual-keys";
import type { VirtualKeyInventoryItem } from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { formatCents } from "@/shared/lib/format-currency";
import { PageHeader } from "@/shared/components/PageHeader";
import { StatusBadge } from "@/shared/components/StatusBadge";
import { formatDateTime, formatRelativeFromNow } from "@/features/providers/lib/format";
import { getProblemDetail } from "@/shared/api/problem-detail";
import { keyStatusPresentation } from "@/features/projects/lib/key-status";
import { canViewTeam } from "@/features/auth/lib/permissions";
import { useMeApiV1AuthMeGet } from "@/shared/api/generated/auth/auth";

const PAGE_SIZE = 25;
const STALE_KEY_DAYS = 30;
type InventoryStatus =
  | "all"
  | "active"
  | "unused"
  | "expiring_soon"
  | "expired"
  | "revoked"
  | "project_archived"
  | "team_archived"
  | "no_effective_access";
type InventoryUsage = "all" | "used" | "never";

export function VirtualKeysPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [status, setStatus] = useState<InventoryStatus>("all");
  const [teamId, setTeamId] = useState("all");
  const [projectId, setProjectId] = useState("all");
  const [usage, setUsage] = useState<InventoryUsage>("all");
  const [offset, setOffset] = useState(0);
  const [revokeKey, setRevokeKey] = useState<VirtualKeyInventoryItem | null>(null);
  const [revokeReason, setRevokeReason] = useState("");

  const inventoryQuery = useListVirtualKeyInventoryApiV1VirtualKeysGet({
    search: deferredSearch || undefined,
    status: status === "all" ? undefined : status,
    team_id: teamId === "all" ? undefined : teamId,
    project_id: projectId === "all" ? undefined : projectId,
    usage: usage === "all" ? undefined : usage,
    limit: PAGE_SIZE,
    offset,
  });
  const projectsQuery = useListProjectsApiV1ProjectsGet();
  const teamsQuery = useListTeamsApiV1TeamsGet();
  const currentUserQuery = useMeApiV1AuthMeGet();
  const currentUser = currentUserQuery.data?.status === 200 ? currentUserQuery.data.data : null;
  const page = inventoryQuery.data?.status === 200 ? inventoryQuery.data.data : undefined;
  const projects = projectsQuery.data?.status === 200 ? projectsQuery.data.data : [];
  const teams = teamsQuery.data?.status === 200 ? teamsQuery.data.data : [];
  const revokeImpactQuery =
    useGetVirtualKeyRevokeImpactApiV1ProjectsProjectIdKeysKeyIdRevokeImpactGet(
      revokeKey?.project_id ?? "",
      revokeKey?.id ?? "",
      { query: { enabled: Boolean(revokeKey) } },
    );
  const revokeImpact = revokeImpactQuery.data?.status === 200 ? revokeImpactQuery.data.data : null;

  const revokeMutation = useRevokeVirtualKeyApiV1ProjectsProjectIdKeysKeyIdDelete({
    mutation: {
      onSuccess: async () => {
        setRevokeKey(null);
        setRevokeReason("");
        await queryClient.invalidateQueries();
      },
      onError: (error) => toast.error(getProblemDetail(error, "Virtual key could not be revoked.")),
    },
  });

  const resetOffset = (update: () => void) => {
    update();
    setOffset(0);
  };
  const hasPrevious = offset > 0;
  const hasNext = Boolean(page && offset + page.items.length < page.total);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Virtual Keys"
        description="Organization inventory of application credentials across accessible projects."
      />
      <Card>
        <CardHeader>
          <CardTitle>Virtual key inventory</CardTitle>
          <CardDescription>
            {page ? `${page.total} matching keys` : "Loading inventory..."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className="relative xl:col-span-2">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-9"
                value={search}
                onChange={(event) => resetOffset(() => setSearch(event.target.value))}
                placeholder="Search name or safe prefix..."
              />
            </div>
            <InventorySelect
              value={teamId}
              onChange={(value) => resetOffset(() => setTeamId(value))}
              label="Team"
            >
              <SelectItem value="all">All teams</SelectItem>
              {teams.map((team) => (
                <SelectItem key={team.id} value={team.id}>
                  {team.name}
                </SelectItem>
              ))}
            </InventorySelect>
            <InventorySelect
              value={projectId}
              onChange={(value) => resetOffset(() => setProjectId(value))}
              label="Project"
            >
              <SelectItem value="all">All projects</SelectItem>
              {projects.map((project) => (
                <SelectItem key={project.id} value={project.id}>
                  {project.name}
                </SelectItem>
              ))}
            </InventorySelect>
            <InventorySelect
              value={status}
              onChange={(value) => resetOffset(() => setStatus(value as InventoryStatus))}
              label="Status"
            >
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Active</SelectItem>
              <SelectItem value="unused">Unused</SelectItem>
              <SelectItem value="expiring_soon">Expiring soon</SelectItem>
              <SelectItem value="expired">Expired</SelectItem>
              <SelectItem value="revoked">Revoked</SelectItem>
              <SelectItem value="project_archived">Project archived</SelectItem>
              <SelectItem value="team_archived">Team archived</SelectItem>
              <SelectItem value="no_effective_access">No effective access</SelectItem>
            </InventorySelect>
            <InventorySelect
              value={usage}
              onChange={(value) => resetOffset(() => setUsage(value as InventoryUsage))}
              label="Usage"
            >
              <SelectItem value="all">Any usage</SelectItem>
              <SelectItem value="used">Used</SelectItem>
              <SelectItem value="never">Never used</SelectItem>
            </InventorySelect>
          </div>

          {inventoryQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Loading virtual keys...</p>
          ) : !page?.items.length ? (
            <EmptyState icon={KeyRound} title="No keys match" description="Try another filter." />
          ) : (
            <>
              {isMobile ? (
                <div className="grid gap-3">
                  {page.items.map((key) => (
                    <InventoryKeyCard
                      key={key.id}
                      virtualKey={key}
                      canOpenTeam={canViewTeam(currentUser, key.team_id)}
                      onOpen={() => navigate(`/projects/${key.project_id}/keys/${key.id}`)}
                      onRevoke={() => setRevokeKey(key)}
                    />
                  ))}
                </div>
              ) : (
                <DataTable
                  columns={[
                    {
                      key: "name",
                      header: "Name",
                      cell: (key) => (
                        <>
                          <Link
                            to={`/projects/${key.project_id}/keys/${key.id}`}
                            onClick={(event) => event.stopPropagation()}
                            className="font-medium underline-offset-4 hover:underline"
                          >
                            {key.name}
                          </Link>
                          <div className="font-mono text-xs text-muted-foreground">
                            {key.key_prefix}
                          </div>
                        </>
                      ),
                    },
                    {
                      key: "project",
                      header: "Project",
                      cell: (key) => (
                        <Link
                          to={`/projects/${key.project_id}`}
                          onClick={(event) => event.stopPropagation()}
                          className="hover:underline"
                        >
                          {key.project_name}
                        </Link>
                      ),
                    },
                    {
                      key: "team",
                      header: "Team",
                      cell: (key) => (
                        <Link
                          to={`/teams/${key.team_id}`}
                          onClick={(event) => event.stopPropagation()}
                          className="hover:underline"
                        >
                          {key.team_name}
                        </Link>
                      ),
                    },
                    {
                      key: "status",
                      header: "Status",
                      cell: (key) => <KeyOperationalStatus status={key.status} />,
                    },
                    {
                      key: "creator",
                      header: "Creator",
                      className: "text-muted-foreground",
                      cell: (key) => key.creator_name ?? key.creator_email ?? "Legacy",
                    },
                    {
                      key: "last_used",
                      header: "Last used",
                      className: "text-muted-foreground",
                      cell: (key) => (
                        <span title={key.last_used_at ? formatDateTime(key.last_used_at) : undefined}>
                          {keyUsageLabel(key.last_used_at)}
                        </span>
                      ),
                    },
                    {
                      key: "actions",
                      header: <span className="sr-only">Actions</span>,
                      headClassName: "w-12",
                      cell: (key) =>
                        key.can_manage && !key.revoked_at ? (
                          <div onClick={(event) => event.stopPropagation()}>
                            <Button
                              variant="ghost"
                              size="icon"
                              aria-label={`Revoke ${key.name}`}
                              onClick={() => setRevokeKey(key)}
                            >
                              <Trash2 />
                            </Button>
                          </div>
                        ) : null,
                    },
                  ]}
                  data={page.items}
                  getRowKey={(key) => key.id}
                  onRowClick={(key) => navigate(`/projects/${key.project_id}/keys/${key.id}`)}
                />
              )}
            </>
          )}
          <div className="flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              {page ? `${offset + 1}-${offset + page.items.length} of ${page.total}` : ""}
            </span>
            <div className="flex gap-2">
              <Button
                variant="outline"
                disabled={!hasPrevious}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="outline"
                disabled={!hasNext}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={Boolean(revokeKey)} onOpenChange={(open) => !open && setRevokeKey(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke {revokeKey?.name}?</DialogTitle>
            <DialogDescription>
              This immediately and permanently disables the key.
            </DialogDescription>
          </DialogHeader>
          {revokeImpactQuery.isPending ? (
            <p className="text-sm text-muted-foreground">Checking impact...</p>
          ) : revokeImpact ? (
            <div className="space-y-3">
              <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm md:grid-cols-3">
                <ImpactFact
                  label="Last used"
                  value={
                    revokeImpact.last_used_at
                      ? new Date(revokeImpact.last_used_at).toLocaleString()
                      : "Never"
                  }
                />
                <ImpactFact
                  label={`${revokeImpact.recent_usage_window_days}d requests`}
                  value={(revokeImpact.recent_request_count ?? 0).toLocaleString()}
                />
                <ImpactFact
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
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm text-destructive">Impact could not be loaded.</p>
              <Button variant="outline" size="sm" onClick={() => revokeImpactQuery.refetch()}>
                Retry
              </Button>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="inventory-revoke-reason">Reason</Label>
            <Textarea
              id="inventory-revoke-reason"
              value={revokeReason}
              maxLength={500}
              onChange={(event) => setRevokeReason(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={!revokeReason.trim() || revokeMutation.isPending || !revokeImpact}
              onClick={() =>
                revokeKey &&
                revokeMutation.mutate({
                  projectId: revokeKey.project_id,
                  keyId: revokeKey.id,
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
    </div>
  );
}

function InventoryKeyCard({
  virtualKey,
  canOpenTeam,
  onOpen,
  onRevoke,
}: {
  virtualKey: VirtualKeyInventoryItem;
  canOpenTeam: boolean;
  onOpen: () => void;
  onRevoke: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      className="rounded-lg border bg-card p-4 shadow-sm transition-colors hover:bg-muted/30"
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/projects/${virtualKey.project_id}/keys/${virtualKey.id}`}
            onClick={(event) => event.stopPropagation()}
            className="font-medium underline-offset-4 hover:underline"
          >
            {virtualKey.name}
          </Link>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{virtualKey.key_prefix}</p>
        </div>
        <KeyOperationalStatus status={virtualKey.status} />
      </div>
      <div className="mt-3 grid gap-3 text-sm">
        <div className="flex flex-wrap gap-2">
          <Link
            to={`/projects/${virtualKey.project_id}`}
            onClick={(event) => event.stopPropagation()}
            className="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
          >
            {virtualKey.project_name}
          </Link>
          {canOpenTeam ? (
            <Link
              to={`/teams/${virtualKey.team_id}`}
              onClick={(event) => event.stopPropagation()}
              className="rounded-md border px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {virtualKey.team_name}
            </Link>
          ) : (
            <span className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
              {virtualKey.team_name}
            </span>
          )}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <p className="text-xs text-muted-foreground">Creator</p>
            <p className="text-sm font-medium">
              {virtualKey.creator_name ?? virtualKey.creator_email ?? "Legacy"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Last used</p>
            <p className="text-sm font-medium">{keyUsageLabel(virtualKey.last_used_at)}</p>
          </div>
        </div>
      </div>
      {virtualKey.can_manage && !virtualKey.revoked_at ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-4 w-full"
          onClick={(event) => {
            event.stopPropagation();
            onRevoke();
          }}
        >
          <Trash2 />
          Revoke
        </Button>
      ) : null}
    </div>
  );
}

function KeyOperationalStatus({ status }: { status: string }) {
  const presentation = keyStatusPresentation(status);
  return (
    <div className="flex max-w-64 flex-col gap-1">
      <StatusBadge variant={presentation.variant}>{presentation.label}</StatusBadge>
      {presentation.category !== "credential" || status !== "active" ? (
        <span className="text-xs text-muted-foreground">{presentation.reason}</span>
      ) : null}
    </div>
  );
}

function InventorySelect({
  value,
  onChange,
  label,
  children,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  children: ReactNode;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>{children}</SelectContent>
    </Select>
  );
}

function ImpactFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

function keyUsageLabel(lastUsedAt: string | null | undefined) {
  if (!lastUsedAt) return "Never used";
  const ageMs = Date.now() - new Date(lastUsedAt).getTime();
  const ageDays = Math.floor(ageMs / 86_400_000);
  if (ageDays >= STALE_KEY_DAYS) return `Unused for ${ageDays}d`;
  return formatRelativeFromNow(lastUsedAt);
}

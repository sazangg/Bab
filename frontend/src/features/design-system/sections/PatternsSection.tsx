import { MoreHorizontal, Pencil, Plug, Plus, Power, Search } from "lucide-react";

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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
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
import { StatusBadge } from "@/shared/components/StatusBadge";
import { cn } from "@/lib/utils";

import { Example, Section } from "../components/Section";

const sampleRows = [
  {
    name: "Mobile platform",
    slug: "mobile-platform",
    projects: 4,
    description: "Apps and SDKs serving consumers.",
    status: "active" as const,
    updated: "2h ago",
  },
  {
    name: "Data infra",
    slug: "data-infra",
    projects: 7,
    description: "Pipelines, warehousing, embeddings.",
    status: "active" as const,
    updated: "5d ago",
  },
  {
    name: "Legacy mobile",
    slug: "legacy-mobile",
    projects: 1,
    description: "Pre-2024 native apps. Frozen.",
    status: "inactive" as const,
    updated: "1mo ago",
  },
];

export function PatternsSection() {
  return (
    <Section
      id="patterns"
      title="Patterns"
      description="Composed surfaces — the exact recipes the app uses. Copy these when you build new screens so the rhythm stays consistent."
    >
      <Example
        label="PageHeader with actions"
        description="One per page, top of the content area. Title + description + action cluster."
      >
        <PageHeader
          title="Teams"
          description="Teams group projects under a business, product, or division boundary."
          actions={
            <Button>
              <Plus />
              New team
            </Button>
          }
        />
      </Example>

      <Example
        label="Filter toolbar"
        description="Sits inside the list Card's CardContent, above the table. Search on the left, filters on the right."
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="relative max-w-md flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input className="pl-9" placeholder="Search projects..." />
          </div>
          <div className="flex items-center gap-2">
            <Select defaultValue="all">
              <SelectTrigger className="h-9 w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All teams</SelectItem>
                <SelectItem value="t1">Mobile platform</SelectItem>
                <SelectItem value="t2">Data infra</SelectItem>
              </SelectContent>
            </Select>
            <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
              {["All", "Active", "Archived"].map((label, index) => (
                <button
                  key={label}
                  type="button"
                  className={
                    index === 1
                      ? "rounded bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-sm"
                      : "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  }
                >
                  {label}
                  <span className="ml-1.5 text-muted-foreground">
                    {label === "All" ? 12 : label === "Active" ? 9 : 3}
                  </span>
                </button>
              ))}
            </div>
          </div>
        </div>
      </Example>

      <Example
        label="Admin list (Card + Table)"
        description="Default shape for all admin list pages. PageHeader handles the main CTA; the Card holds toolbar + table."
      >
        <Card>
          <CardHeader>
            <CardTitle>All teams</CardTitle>
            <CardDescription>3 teams · 2 active · 1 archived</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative max-w-md flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-9" placeholder="Search teams..." />
              </div>
              <div className="flex items-center gap-1 rounded-md border bg-muted/30 p-0.5">
                {["All", "Active", "Archived"].map((label, index) => (
                  <button
                    key={label}
                    type="button"
                    className={
                      index === 1
                        ? "rounded bg-background px-2.5 py-1 text-xs font-medium text-foreground shadow-sm"
                        : "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                    }
                  >
                    {label}
                    <span className="ml-1.5 text-muted-foreground">
                      {label === "All" ? 3 : label === "Active" ? 2 : 1}
                    </span>
                  </button>
                ))}
              </div>
            </div>
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead className="text-right">Projects</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Updated</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sampleRows.map((row) => (
                    <TableRow
                      key={row.slug}
                      className={cn("cursor-pointer", row.status === "inactive" && "opacity-60")}
                    >
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {row.slug}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {row.projects}
                      </TableCell>
                      <TableCell className="max-w-md truncate text-muted-foreground">
                        {row.description}
                      </TableCell>
                      <TableCell>
                        <StatusBadge variant={row.status === "active" ? "active" : "inactive"}>
                          {row.status === "active" ? "Active" : "Archived"}
                        </StatusBadge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">{row.updated}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </Example>

      <Example
        label="Catalog card row"
        description="Use when each item has rich visual identity (logo, multiple status chips, base URL). Default in /providers."
      >
        <div className="space-y-3">
          <CatalogRowDemo
            name="OpenAI"
            description="Official OpenAI API for GPT models."
            url="https://api.openai.com/v1"
            statusLabel="Configured"
            statusVariant="active"
            badge="2 active credentials"
          />
          <CatalogRowDemo
            name="Anthropic"
            description="Claude models via the OpenAI-compatible endpoint."
            url="https://api.anthropic.com/v1"
            statusLabel="Not configured"
            statusVariant="inactive"
          />
        </div>
      </Example>

      <Example
        label="Summary card + Resources card"
        description="Detail-page rhythm: summary at the top, then a Card per resource section. Mirror this for Team, Project, Provider detail."
      >
        <div className="flex flex-col gap-6">
          <PageHeader
            title="Mobile platform"
            description="Apps and SDKs serving consumers."
            actions={
              <div className="flex items-center gap-2">
                <Button variant="outline">
                  <Pencil />
                  Edit team
                </Button>
                <Button variant="outline" size="icon" aria-label="More actions">
                  <MoreHorizontal />
                </Button>
              </div>
            }
          />
          <Card>
            <CardHeader>
              <CardTitle>Team summary</CardTitle>
              <CardDescription className="font-mono text-xs">mobile-platform</CardDescription>
              <CardAction>
                <StatusBadge variant="active">Active</StatusBadge>
              </CardAction>
            </CardHeader>
            <CardContent className="grid gap-4 md:grid-cols-4">
              <SummaryFact label="Projects" value="4 active" />
              <SummaryFact label="Total projects" value="6" />
              <SummaryFact label="Created" value="3 months ago" />
              <SummaryFact label="Updated" value="2 hours ago" />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Projects</CardTitle>
              <CardDescription>
                Projects inside this team receive allocations and issue virtual keys.
              </CardDescription>
              <CardAction>
                <Button size="sm">
                  <Plus />
                  New project
                </Button>
              </CardAction>
            </CardHeader>
            <CardContent>
              <div className="rounded-md border border-dashed p-6 text-center">
                <p className="text-sm font-medium">No projects yet</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Create a project to start assigning allocations and keys.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </Example>

      <Example
        label="Two-step inline form"
        description="When a single action has prerequisites (e.g. create provider + add first credential)."
      >
        <div className="space-y-4">
          <div className="rounded-lg border border-dashed bg-muted/30 p-4">
            <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Step 1 · Provider
            </p>
            <p className="mt-1 text-sm">
              <span className="font-medium">Anthropic</span> will be registered with slug{" "}
              <span className="font-mono">anthropic</span> and base URL{" "}
              <span className="font-mono">https://api.anthropic.com/v1</span>.
            </p>
          </div>
          <div className="space-y-3">
            <p className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
              Step 2 · First credential
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <Input placeholder="Credential name" defaultValue="Anthropic credential" />
              <Input placeholder="sk-ant-..." type="password" />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline">Cancel</Button>
            <Button>Set up</Button>
          </div>
        </div>
      </Example>
    </Section>
  );
}

function CatalogRowDemo({
  name,
  description,
  url,
  statusLabel,
  statusVariant,
  badge,
}: {
  name: string;
  description: string;
  url: string;
  statusLabel: string;
  statusVariant: "active" | "inactive";
  badge?: string;
}) {
  return (
    <div className="rounded-lg border p-4 transition-colors hover:bg-muted/30">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0 flex-1 space-y-2">
          <div className="flex items-center gap-3">
            <div
              className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-background"
              aria-hidden="true"
            >
              <Plug className="size-4 text-muted-foreground" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-medium">{name}</h2>
                <StatusBadge variant={statusVariant}>{statusLabel}</StatusBadge>
                {badge ? <span className="text-xs text-muted-foreground">{badge}</span> : null}
              </div>
              <p className="text-sm text-muted-foreground">{description}</p>
            </div>
          </div>
          <p className="truncate font-mono text-xs text-muted-foreground">{url}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button size="sm">
            <Plus />
            {statusVariant === "active" ? "Add credential" : "Set up"}
          </Button>
          {statusVariant === "active" ? (
            <>
              <Button size="sm" variant="outline">
                Open
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label="Actions">
                    <MoreHorizontal />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem>
                    <Pencil className="mr-2 size-4" />
                    Edit
                  </DropdownMenuItem>
                  <DropdownMenuItem variant="destructive">
                    <Power className="mr-2 size-4" />
                    Deactivate
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function SummaryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="truncate text-sm font-medium">{value}</p>
    </div>
  );
}

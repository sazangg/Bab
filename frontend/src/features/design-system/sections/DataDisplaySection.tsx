import { KeyRound, Pencil, Plus } from "lucide-react";

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { Caption, Example, Section } from "../components/Section";

const tableRows = [
  { name: "Mobile platform", slug: "mobile-platform", projects: 4, status: "active" as const },
  { name: "Data infra", slug: "data-infra", projects: 7, status: "active" as const },
  { name: "Legacy mobile", slug: "legacy-mobile", projects: 1, status: "inactive" as const },
];

export function DataDisplaySection() {
  return (
    <Section
      id="data-display"
      title="Data display & navigation"
      description="Surfaces that present records and let users move between them."
    >
      <Example
        label="Card — anatomy"
        description="Header + description + optional action + content + optional footer."
      >
        <Card className="max-w-md">
          <CardHeader>
            <CardTitle>Provider summary</CardTitle>
            <CardDescription>https://api.openai.com/v1</CardDescription>
            <CardAction>
              <StatusBadge variant="active">Active</StatusBadge>
            </CardAction>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <p className="text-xs text-muted-foreground">Integration</p>
              <p className="font-medium">openai_compatible</p>
            </div>
            <div>
              <p className="text-xs text-muted-foreground">Routing</p>
              <p className="font-medium">Priority</p>
            </div>
          </CardContent>
          <CardFooter>
            <Caption>last synced 2 minutes ago</Caption>
          </CardFooter>
        </Card>
      </Example>

      <Example
        label="Card — summary fact grid"
        description="grid-cols-4 stat row beneath the header. Use for resource overview."
      >
        <Card>
          <CardHeader>
            <CardTitle>Team summary</CardTitle>
            <CardDescription className="font-mono text-xs">mobile-platform</CardDescription>
            <CardAction>
              <StatusBadge variant="active">Active</StatusBadge>
            </CardAction>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-4">
            <Fact label="Projects" value="4 active" />
            <Fact label="Total projects" value="6" />
            <Fact label="Created" value="3 months ago" />
            <Fact label="Updated" value="2 hours ago" />
          </CardContent>
        </Card>
      </Example>

      <Example label="Table — basic" description="Use shadcn Table inside a Card for admin lists.">
        <Card>
          <CardHeader>
            <CardTitle>All teams</CardTitle>
            <CardDescription>3 teams · 2 active · 1 archived</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="overflow-hidden rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Slug</TableHead>
                    <TableHead className="text-right">Projects</TableHead>
                    <TableHead>Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tableRows.map((row) => (
                    <TableRow
                      key={row.slug}
                      className={row.status === "inactive" ? "opacity-60" : undefined}
                    >
                      <TableCell className="font-medium">{row.name}</TableCell>
                      <TableCell className="font-mono text-xs text-muted-foreground">
                        {row.slug}
                      </TableCell>
                      <TableCell className="text-right tabular-nums text-muted-foreground">
                        {row.projects}
                      </TableCell>
                      <TableCell>
                        <StatusBadge variant={row.status === "active" ? "active" : "inactive"}>
                          {row.status === "active" ? "Active" : "Archived"}
                        </StatusBadge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </Example>

      <Example label="Tabs" description="Use to split detail-page content by subject.">
        <Tabs defaultValue="keys" className="space-y-4">
          <TabsList>
            <TabsTrigger value="keys">
              <KeyRound className="size-3.5" />
              Keys (4)
            </TabsTrigger>
            <TabsTrigger value="policies">Policies</TabsTrigger>
            <TabsTrigger value="controls">Controls</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>
          <TabsContent value="keys">
            <p className="text-sm text-muted-foreground">Keys tab content.</p>
          </TabsContent>
          <TabsContent value="policies">
            <p className="text-sm text-muted-foreground">Policies tab content.</p>
          </TabsContent>
          <TabsContent value="controls">
            <p className="text-sm text-muted-foreground">Limits tab content.</p>
          </TabsContent>
          <TabsContent value="activity">
            <p className="text-sm text-muted-foreground">Activity tab content.</p>
          </TabsContent>
        </Tabs>
      </Example>

      <Example label="Breadcrumb" description="Reflects the route — wired in DashboardLayout.">
        <Breadcrumb>
          <BreadcrumbList>
            <BreadcrumbItem>
              <BreadcrumbLink href="#">Teams</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbLink href="#">Mobile platform</BreadcrumbLink>
            </BreadcrumbItem>
            <BreadcrumbSeparator />
            <BreadcrumbItem>
              <BreadcrumbPage>Checkout API</BreadcrumbPage>
            </BreadcrumbItem>
          </BreadcrumbList>
        </Breadcrumb>
      </Example>

      <Example
        label="Segment toggle"
        description="Custom button group used for status filters. Active state uses elevated background."
      >
        <SegmentToggleDemo />
      </Example>
    </Section>
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

function SegmentToggleDemo() {
  return (
    <div className="flex items-center gap-3">
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
      <Button size="sm" variant="outline">
        <Pencil />
        Edit
      </Button>
      <Button size="sm">
        <Plus />
        New
      </Button>
    </div>
  );
}

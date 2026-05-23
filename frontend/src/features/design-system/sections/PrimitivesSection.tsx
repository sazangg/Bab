import { useState } from "react";
import { Bold, Check, Italic, Plus, Search, Underline } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Toggle } from "@/components/ui/toggle";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { Caption, Example, Section } from "../components/Section";

const buttonVariants = ["default", "outline", "secondary", "ghost", "destructive", "link"] as const;
const buttonSizes = ["xs", "sm", "default", "lg"] as const;
const badgeVariants = ["default", "secondary", "destructive", "outline", "ghost"] as const;
const statusVariants = [
  "active",
  "inactive",
  "success",
  "error",
  "revoked",
  "expired",
  "muted",
] as const;

export function PrimitivesSection() {
  const [switchOn, setSwitchOn] = useState(true);
  const [checkboxOn, setCheckboxOn] = useState(true);
  const [textValue, setTextValue] = useState("");

  return (
    <Section
      id="primitives"
      title="Primitives"
      description="Atomic building blocks. Mix and match these to compose every surface."
    >
      <Example
        label="Button — variants"
        description="Prefer default for primary actions. Use destructive only for actions that delete or break state."
      >
        <div className="flex flex-wrap items-center gap-3">
          {buttonVariants.map((variant) => (
            <Button key={variant} variant={variant}>
              {variant.charAt(0).toUpperCase() + variant.slice(1)}
            </Button>
          ))}
        </div>
      </Example>

      <Example label="Button — sizes" description="xs and sm fit inside dense tables and toolbars.">
        <div className="flex flex-wrap items-center gap-3">
          {buttonSizes.map((size) => (
            <Button key={size} size={size}>
              <Plus />
              Size {size}
            </Button>
          ))}
        </div>
      </Example>

      <Example label="Button — icon" description="Use icon variants for toolbar actions.">
        <div className="flex flex-wrap items-center gap-3">
          <Button size="icon-xs" aria-label="Add">
            <Plus />
          </Button>
          <Button size="icon-sm" aria-label="Add">
            <Plus />
          </Button>
          <Button size="icon" aria-label="Add">
            <Plus />
          </Button>
          <Button size="icon-lg" aria-label="Add">
            <Plus />
          </Button>
        </div>
      </Example>

      <Example label="Button — states">
        <div className="flex flex-wrap items-center gap-3">
          <Button>Default</Button>
          <Button disabled>Disabled</Button>
          <Button variant="outline" disabled>
            Disabled outline
          </Button>
          <Button variant="destructive" disabled>
            Disabled destructive
          </Button>
        </div>
      </Example>

      <Example label="Badge — variants">
        <div className="flex flex-wrap items-center gap-2">
          {badgeVariants.map((variant) => (
            <Badge key={variant} variant={variant}>
              {variant}
            </Badge>
          ))}
        </div>
      </Example>

      <Example
        label="StatusBadge"
        description="Semantic wrapper over Badge. Use for record state — provider status, credential health, project archive state."
      >
        <div className="flex flex-wrap items-center gap-2">
          {statusVariants.map((variant) => (
            <StatusBadge key={variant} variant={variant}>
              {variant}
            </StatusBadge>
          ))}
        </div>
      </Example>

      <Example label="Input — variants">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="ds-input-default">Default</Label>
            <Input
              id="ds-input-default"
              placeholder="Type here..."
              value={textValue}
              onChange={(e) => setTextValue(e.target.value)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ds-input-icon">With icon</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input id="ds-input-icon" className="pl-9" placeholder="Search teams..." />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ds-input-disabled">Disabled</Label>
            <Input id="ds-input-disabled" disabled value="Read-only" readOnly />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="ds-input-error">With error</Label>
            <Input id="ds-input-error" aria-invalid="true" defaultValue="invalid value" />
            <p className="text-xs text-destructive">Must be at least 3 characters.</p>
          </div>
        </div>
      </Example>

      <Example label="Textarea">
        <div className="space-y-1.5">
          <Label htmlFor="ds-textarea">Description</Label>
          <Textarea id="ds-textarea" rows={3} placeholder="Tell us about this team..." />
        </div>
      </Example>

      <Example label="Select">
        <div className="space-y-1.5">
          <Label htmlFor="ds-select">Routing policy</Label>
          <Select defaultValue="priority">
            <SelectTrigger id="ds-select" className="w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="priority">Priority</SelectItem>
              <SelectItem value="round_robin">Round robin</SelectItem>
              <SelectItem value="least_recently_used">Least recently used</SelectItem>
              <SelectItem value="health_based">Health based</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </Example>

      <Example label="Switch + Checkbox">
        <div className="flex flex-wrap items-center gap-8">
          <Label className="flex items-center gap-2 text-sm font-medium">
            <Switch checked={switchOn} onCheckedChange={setSwitchOn} />
            <span>Enabled</span>
          </Label>
          <Label className="flex items-center gap-2 text-sm font-medium">
            <Checkbox checked={checkboxOn} onCheckedChange={(v) => setCheckboxOn(v === true)} />
            <span>Tools enabled</span>
          </Label>
          <Label className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
            <Checkbox disabled />
            <span>Disabled option</span>
          </Label>
        </div>
      </Example>

      <Example label="Toggle / ToggleGroup">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Toggle aria-label="Toggle bold">
              <Bold />
            </Toggle>
            <Toggle variant="outline" aria-label="Toggle italic">
              <Italic />
            </Toggle>
            <Toggle defaultPressed aria-label="Toggle underline">
              <Underline />
            </Toggle>
          </div>
          <ToggleGroup type="single" defaultValue="left" className="w-fit">
            <ToggleGroupItem value="left">Left</ToggleGroupItem>
            <ToggleGroupItem value="center">Center</ToggleGroupItem>
            <ToggleGroupItem value="right">Right</ToggleGroupItem>
          </ToggleGroup>
        </div>
      </Example>

      <Example label="Skeleton" description="Use during initial load to preserve layout.">
        <div className="space-y-3">
          <Skeleton className="h-4 w-48" />
          <Skeleton className="h-4 w-64" />
          <Skeleton className="h-4 w-32" />
        </div>
      </Example>

      <Example label="Separator">
        <div className="space-y-3 text-sm">
          <p>Top content</p>
          <Separator />
          <p className="text-muted-foreground">Below the separator</p>
        </div>
        <div className="mt-4 flex items-center gap-3 text-sm">
          <p>Left</p>
          <Separator orientation="vertical" className="h-6" />
          <p className="text-muted-foreground">Right</p>
        </div>
      </Example>

      <Example label="Label + helper text" description="Standard form-field stack.">
        <div className="space-y-1.5">
          <Label htmlFor="ds-helper">Slug</Label>
          <Input id="ds-helper" defaultValue="mobile-division" className="font-mono" />
          <p className="text-xs text-muted-foreground">
            Will be created as <span className="font-mono text-foreground">mobile-division</span>.
          </p>
        </div>
      </Example>

      <Example label="Inline icon + meta">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Check className="size-3 text-emerald-500" />
          <span>Saved 2 minutes ago</span>
          <Caption>typical row meta</Caption>
        </div>
      </Example>
    </Section>
  );
}

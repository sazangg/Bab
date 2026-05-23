import { useState } from "react";
import { Building2, Info, Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
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
  SheetTrigger,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { EmptyState } from "@/shared/components/EmptyState";

import { Example, Section } from "../components/Section";

export function OverlaysFeedbackSection() {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <Section
      id="overlays-feedback"
      title="Overlays & feedback"
      description="Anything that floats above the page or communicates state change."
    >
      <Example
        label="Dialog"
        description="Use for confirmations and short forms. Pair destructive actions with a destructive button."
      >
        <div className="flex flex-wrap items-center gap-3">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Info />
                Info dialog
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Rotate this credential?</DialogTitle>
                <DialogDescription>
                  The current key will stop working immediately and the new key will become the
                  highest priority.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button>Rotate</Button>
                <DialogClose asChild>
                  <Button variant="outline">Cancel</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button variant="destructive">
                <Trash2 />
                Destructive dialog
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Archive this project?</DialogTitle>
                <DialogDescription>
                  The project will stop accepting new requests. Existing virtual keys remain visible
                  but cannot be used.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="destructive" onClick={() => setDialogOpen(false)}>
                  Archive project
                </Button>
                <DialogClose asChild>
                  <Button variant="outline">Cancel</Button>
                </DialogClose>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </Example>

      <Example
        label="Sheet"
        description="Use for longer forms — create/edit flows where Dialog would feel cramped."
      >
        <Sheet>
          <SheetTrigger asChild>
            <Button>
              <Plus />
              Open sheet
            </Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>New team</SheetTitle>
              <SheetDescription>Create a team that will own one or more projects.</SheetDescription>
            </SheetHeader>
            <form className="grid gap-4 px-4" onSubmit={(e) => e.preventDefault()}>
              <div className="space-y-1.5">
                <Label htmlFor="ds-sheet-name">Name</Label>
                <Input id="ds-sheet-name" placeholder="Mobile platform" />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ds-sheet-slug">Slug</Label>
                <Input id="ds-sheet-slug" className="font-mono" placeholder="mobile-platform" />
              </div>
            </form>
            <SheetFooter>
              <Button>Create team</Button>
              <SheetClose asChild>
                <Button variant="outline">Cancel</Button>
              </SheetClose>
            </SheetFooter>
          </SheetContent>
        </Sheet>
      </Example>

      <Example label="Dropdown menu" description="Per-row actions, account menu, switcher.">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline">Team actions</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-56">
            <DropdownMenuLabel>Actions</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <Pencil className="mr-2 size-4" />
              Edit team
            </DropdownMenuItem>
            <DropdownMenuItem>
              <Building2 className="mr-2 size-4" />
              View team
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive">
              <Trash2 className="mr-2 size-4" />
              Archive team
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Example>

      <Example label="Tooltip" description="Short, non-essential hints. Avoid for required info.">
        <div className="flex flex-wrap items-center gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline" size="icon-sm" aria-label="Add credential">
                <Plus />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Add a credential</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="outline">Hover me</Button>
            </TooltipTrigger>
            <TooltipContent>Probes the highest-priority active credential.</TooltipContent>
          </Tooltip>
        </div>
      </Example>

      <Example label="Toast" description="Sonner, mounted globally. Use for action outcomes.">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" onClick={() => toast("Plain message")}>
            Default
          </Button>
          <Button variant="outline" onClick={() => toast.success("Team created.")}>
            Success
          </Button>
          <Button variant="outline" onClick={() => toast.error("Slug already in use.")}>
            Error
          </Button>
          <Button
            variant="outline"
            onClick={() =>
              toast.message("Sync started", {
                description: "12 models will be refreshed in the background.",
              })
            }
          >
            With description
          </Button>
        </div>
      </Example>

      <Example
        label="Alert"
        description="Use inline alerts for static, in-page guidance. For action outcomes prefer a toast."
      >
        <div className="space-y-3">
          <Alert>
            <Info />
            <AlertTitle>Heads up</AlertTitle>
            <AlertDescription>
              You're viewing a demo workspace. Changes apply only to this account.
            </AlertDescription>
          </Alert>
          <Alert variant="destructive">
            <Info />
            <AlertTitle>Provider could not be reached</AlertTitle>
            <AlertDescription>
              The connectivity probe returned 503. Verify the credential or try again later.
            </AlertDescription>
          </Alert>
        </div>
      </Example>

      <Example
        label="EmptyState"
        description="Use when there's nothing to show yet, or filtering wiped the list."
      >
        <EmptyState
          icon={Building2}
          title="No teams yet"
          description="Create the first team to start organizing projects."
          action={
            <Button>
              <Plus />
              New team
            </Button>
          }
        />
      </Example>
    </Section>
  );
}

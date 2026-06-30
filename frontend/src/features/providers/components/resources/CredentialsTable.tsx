import { zodResolver } from "@hookform/resolvers/zod";
import { Activity, ChevronDown, Pencil, Power, RefreshCw, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
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
} from "@/components/ui/sheet";
import type { ProviderCredentialResponse } from "@/shared/api/generated/schemas";
import { StatusBadge } from "@/shared/components/StatusBadge";

import { formatRelativeFromNow, sanitizeCredentialValidationMessage } from "../../lib/format";
import { formatHealth } from "../../lib/resources-helpers";

export function CredentialsTable({
  providerId,
  credentials,
  isLoading,
  isError,
  isTesting,
  onUpdate,
  onRotate,
  onDeactivate,
  onReactivate,
  onTest,
  canManage,
  emptyAction,
}: {
  providerId: string;
  credentials: ProviderCredentialResponse[];
  isLoading: boolean;
  isError: boolean;
  isTesting: boolean;
  onUpdate: (credential: ProviderCredentialResponse, values: { name: string }) => void;
  onRotate: (credential: ProviderCredentialResponse, apiKey: string) => Promise<boolean>;
  onDeactivate: (credential: ProviderCredentialResponse) => void;
  onReactivate: (credential: ProviderCredentialResponse) => void;
  onTest: (credential: ProviderCredentialResponse) => void;
  canManage: boolean;
  emptyAction?: ReactNode;
}) {
  const sortedCredentials = [...credentials].sort(
    (a, b) =>
      Number(b.is_active) - Number(a.is_active) ||
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  );
  const syncCredential = sortedCredentials.find((credential) => credential.is_active);
  const [editCredential, setEditCredential] = useState<ProviderCredentialResponse | null>(null);
  const [rotateCredential, setRotateCredential] = useState<ProviderCredentialResponse | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [isRotating, setIsRotating] = useState(false);

  const columns: DataTableColumn<ProviderCredentialResponse>[] = [
    {
      key: "credential",
      header: "Credential",
      className: "font-medium",
      cell: (credential) => (
        <>
          <div>{credential.name}</div>
          <p className="font-mono text-xs text-muted-foreground">{credential.key_prefix}</p>
          {syncCredential?.id === credential.id ? (
            <p className="text-xs text-muted-foreground">Used first for model sync</p>
          ) : null}
          {credential.failure_message || credential.last_validation_error ? (
            <p className="text-xs text-destructive">
              {credential.failure_reason
                ? `${credential.failure_reason.replaceAll("_", " ")}: `
                : ""}
              {sanitizeCredentialValidationMessage(
                credential.failure_message ?? credential.last_validation_error,
              )}
            </p>
          ) : null}
        </>
      ),
    },
    {
      key: "health",
      header: "Health",
      cell: (credential) => {
        const health = formatHealth(credential.health_status);
        return <StatusBadge variant={health.variant}>{health.label}</StatusBadge>;
      },
    },
    {
      key: "status",
      header: "Status",
      cell: (credential) => (
        <StatusBadge variant={credential.is_active ? "active" : "inactive"}>
          {credential.is_active ? "Active" : "Disabled"}
        </StatusBadge>
      ),
    },
    {
      key: "last_activity",
      header: "Last activity",
      className: "text-xs text-muted-foreground",
      cell: (credential) =>
        credential.last_used_at
          ? formatRelativeFromNow(credential.last_used_at)
          : credential.last_validation_at
            ? `Validated ${formatRelativeFromNow(credential.last_validation_at)}`
            : "Never used",
    },
    ...(canManage
      ? [
          {
            key: "actions",
            header: <span className="sr-only">Actions</span>,
            headClassName: "w-[1%]",
            className: "flex justify-end gap-1",
            cell: (credential: ProviderCredentialResponse) => (
              <>
                <Button
                  size="icon-sm"
                  variant="ghost"
                  disabled={!providerId || !credential.is_active || isTesting}
                  onClick={() => onTest(credential)}
                  title="Test credential"
                  aria-label="Test credential"
                >
                  <Activity />
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button size="icon-sm" variant="ghost" aria-label={`${credential.name} actions`}>
                      <ChevronDown />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setEditCredential(credential)}>
                      <Pencil />
                      Rename
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => setRotateCredential(credential)}>
                      <RefreshCw />
                      Replace secret
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    {credential.is_active ? (
                      <DropdownMenuItem
                        variant="destructive"
                        onSelect={() => onDeactivate(credential)}
                      >
                        <Power />
                        Disable
                      </DropdownMenuItem>
                    ) : (
                      <DropdownMenuItem onSelect={() => onReactivate(credential)}>
                        <RotateCcw />
                        Reactivate
                      </DropdownMenuItem>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            ),
          },
        ]
      : []),
  ];

  return (
    <>
      <DataTable
        columns={columns}
        data={sortedCredentials}
        loading={isLoading}
        error={isError ? "Credentials could not be loaded." : undefined}
        getRowKey={(credential) => credential.id}
        empty={{
          title: "No credentials added yet.",
          description:
            "Add a provider credential before validation, credential pools, and model sync are useful.",
          action: emptyAction,
        }}
      />
      <EditProviderCredentialSheet
        providerCredential={editCredential}
        onClose={() => setEditCredential(null)}
        onSubmit={(values) => {
          if (!editCredential) return;
          onUpdate(editCredential, values);
          setEditCredential(null);
        }}
      />
      <Dialog
        open={Boolean(rotateCredential)}
        onOpenChange={(open) => {
          if (!open) {
            setRotateCredential(null);
            setApiKey("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rotate {rotateCredential?.name ?? "credential"}</DialogTitle>
            <DialogDescription>
              The current key stops working as soon as you save. Make sure the new key is active
              before rotating.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted-foreground">Current prefix</span>
              <span className="font-mono">{rotateCredential?.key_prefix ?? "—"}</span>
            </div>
            <Label htmlFor="rotate-api-key" className="text-xs">
              New API key
            </Label>
            <Input
              id="rotate-api-key"
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={!rotateCredential || !apiKey || isRotating}
              onClick={async () => {
                if (!rotateCredential) return;
                setIsRotating(true);
                const succeeded = await onRotate(rotateCredential, apiKey);
                setIsRotating(false);
                if (succeeded) {
                  setRotateCredential(null);
                  setApiKey("");
                }
              }}
            >
              {isRotating ? "Replacing..." : "Replace and test"}
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

function EditProviderCredentialSheet({
  providerCredential,
  onClose,
  onSubmit,
}: {
  providerCredential: ProviderCredentialResponse | null;
  onClose: () => void;
  onSubmit: (values: { name: string }) => void;
}) {
  const form = useForm<{ name: string }>({
    resolver: zodResolver(z.object({ name: z.string().min(1).max(255) })),
    defaultValues: { name: "" },
  });

  useEffect(() => {
    if (providerCredential) {
      form.reset({ name: providerCredential.name });
    }
  }, [providerCredential, form]);

  return (
    <Sheet open={Boolean(providerCredential)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Edit credential</SheetTitle>
          <SheetDescription>
            Rename this provider credential. Pool membership, priority, and weight are managed from
            the Pools tab.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 overflow-y-auto px-6 py-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="edit-provider-key-name">Name</Label>
            <Input id="edit-provider-key-name" autoFocus {...form.register("name")} />
            {form.formState.errors.name ? (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            ) : null}
          </div>
        </form>
        <SheetFooter>
          <Button onClick={form.handleSubmit(onSubmit)}>Save changes</Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

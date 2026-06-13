import { CheckCircle2, ChevronDown, Circle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  CredentialPoolResponse,
  ProviderCredentialResponse,
} from "@/shared/api/generated/schemas";

export function ProviderSetupChecklist({
  providerReady,
  canManage,
  credentials,
  pools,
  hasActiveCredential,
  activeModelCount,
  onAddCredential,
  onTestAllCredentials,
  onCreatePool,
  onOpenPools,
  onOpenModels,
}: {
  providerReady: boolean;
  canManage: boolean;
  credentials: ProviderCredentialResponse[];
  pools: CredentialPoolResponse[];
  hasActiveCredential: boolean;
  activeModelCount: number;
  onAddCredential: () => void;
  onTestAllCredentials: () => void;
  onCreatePool: () => void;
  onOpenPools: () => void;
  onOpenModels: () => void;
}) {
  const [showCompletedChecklist, setShowCompletedChecklist] = useState(false);

  return (
    <div className="rounded-md border bg-muted/15">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <div className="flex items-center gap-2">
          <CheckCircle2
            className={cn("size-4", providerReady ? "text-success" : "text-muted-foreground")}
          />
          <div>
            <p className="text-sm font-medium">
              {providerReady ? "Setup complete" : "Setup checklist"}
            </p>
            <p className="text-xs text-muted-foreground">
              {providerReady
                ? "Credentials, routing pool, and models are ready."
                : "Complete each routing prerequisite, then test a model."}
            </p>
          </div>
        </div>
        {providerReady ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setShowCompletedChecklist((current) => !current)}
          >
            {showCompletedChecklist ? "Hide steps" : "View steps"}
            <ChevronDown
              className={cn("transition-transform", showCompletedChecklist && "rotate-180")}
            />
          </Button>
        ) : null}
      </div>
      {!providerReady || showCompletedChecklist ? (
        <div className="grid gap-3 border-t p-4 md:grid-cols-2 xl:grid-cols-3">
          <SetupStep
            label="Add credential"
            complete={credentials.length > 0}
            action={canManage ? "Add" : undefined}
            onAction={onAddCredential}
          />
          <SetupStep
            label="Validate credential"
            complete={credentials.some((item) => item.is_active && item.health_status === "valid")}
            action={hasActiveCredential ? "Test all" : undefined}
            onAction={onTestAllCredentials}
          />
          <SetupStep
            label="Create active pool"
            complete={pools.some((item) => item.is_active)}
            action={canManage ? "Create" : undefined}
            onAction={onCreatePool}
          />
          <SetupStep
            label="Attach credential"
            complete={pools.some((item) => (item.active_credential_count ?? 0) > 0)}
            action={pools.length > 0 ? "Open pools" : undefined}
            onAction={onOpenPools}
          />
          <SetupStep
            label="Sync or add models"
            complete={activeModelCount > 0}
            action="Open models"
            onAction={onOpenModels}
          />
          <SetupStep
            label="Test request"
            complete={providerReady}
            action={providerReady ? "Playground" : undefined}
            href="/playground"
          />
        </div>
      ) : null}
    </div>
  );
}

function SetupStep({
  label,
  complete,
  action,
  onAction,
  href,
}: {
  label: string;
  complete: boolean;
  action?: string;
  onAction?: () => void;
  href?: string;
}) {
  return (
    <div className="flex min-h-14 items-center justify-between gap-3 rounded-md border px-3 py-2">
      <div className="flex min-w-0 items-center gap-2">
        {complete ? (
          <CheckCircle2 className="size-4 shrink-0 text-success" />
        ) : (
          <Circle className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="text-sm font-medium">{label}</span>
      </div>
      {action && href ? (
        <Button asChild size="sm" variant="ghost">
          <Link to={href}>{action}</Link>
        </Button>
      ) : action && onAction ? (
        <Button size="sm" variant="ghost" onClick={onAction}>
          {action}
        </Button>
      ) : null}
    </div>
  );
}

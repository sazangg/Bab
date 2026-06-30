import { CheckCircle2, ChevronDown, Circle } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  CredentialPoolResponse,
  ProviderCredentialResponse,
} from "@/shared/api/generated/schemas";
import {
  getProviderReadiness,
  providerReadinessActionLabel,
  type ProviderReadinessAction,
} from "../../lib/provider-readiness";

export function ProviderSetupChecklist({
  providerEnabled,
  canManage,
  credentials,
  pools,
  activeModelCount,
  onEnableProvider,
  onAddCredential,
  onTestAllCredentials,
  onCreatePool,
  onOpenPools,
  onOpenModels,
}: {
  providerEnabled: boolean;
  canManage: boolean;
  credentials: ProviderCredentialResponse[];
  pools: CredentialPoolResponse[];
  activeModelCount: number;
  onEnableProvider: () => void;
  onAddCredential: () => void;
  onTestAllCredentials: () => void;
  onCreatePool: () => void;
  onOpenPools: () => void;
  onOpenModels: () => void;
}) {
  const [showCompletedChecklist, setShowCompletedChecklist] = useState(false);
  const readiness = getProviderReadiness({
    providerEnabled,
    credentialCount: credentials.filter((item) => item.is_active).length,
    validatedCredentialCount: credentials.filter(
      (item) => item.is_active && item.health_status === "valid",
    ).length,
    poolCount: pools.filter((item) => item.is_active).length,
    poolsWithCredentialsCount: pools.filter((item) => (item.active_credential_count ?? 0) > 0)
      .length,
    modelCount: activeModelCount,
  });
  const providerReady = readiness.isReady;
  const actionHandlers: Partial<Record<Exclude<ProviderReadinessAction, null>, () => void>> = {
    enable_provider: onEnableProvider,
    add_credential: onAddCredential,
    test_credentials: onTestAllCredentials,
    create_pool: onCreatePool,
    attach_credential: onOpenPools,
    sync_or_add_models: onOpenModels,
  };

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
          {readiness.steps.map((step) => (
            <SetupStep
              key={step.id}
              label={step.label}
              complete={step.complete}
              action={canManage ? providerReadinessActionLabel(step.action) ?? undefined : undefined}
              onAction={step.action ? actionHandlers[step.action] : undefined}
            />
          ))}
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

/* eslint-disable react-refresh/only-export-components -- hook factory that returns its dialog element; this module is not a fast-refresh component boundary */
import { useState } from "react";

import { ImpactConfirmationDialog } from "@/shared/components/ImpactConfirmationDialog";
import type { GuardrailImpactResponse } from "@/shared/api/generated/schemas";

type GuardrailImpactRequest = {
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  fetchImpact: () => Promise<{ status: number; data: unknown }>;
  onConfirm: () => void;
};

/**
 * Canonical impact-gated confirmation for guardrail mutations. Opens the shared
 * ImpactConfirmationDialog immediately, loads the impact (with its own loading / error /
 * retry states), and runs `onConfirm` only when the operator confirms. Replaces the old
 * `window.confirm`-based `confirmGuardrailImpact`.
 */
export function useGuardrailImpactConfirmation() {
  const [request, setRequest] = useState<GuardrailImpactRequest | null>(null);
  const [impact, setImpact] = useState<GuardrailImpactResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [hasError, setHasError] = useState(false);

  const load = async (target: GuardrailImpactRequest) => {
    setIsLoading(true);
    setHasError(false);
    try {
      const response = await target.fetchImpact();
      if (response.status !== 200) {
        setHasError(true);
        return;
      }
      setImpact(response.data as GuardrailImpactResponse);
    } catch {
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  };

  const close = () => {
    setRequest(null);
    setImpact(null);
    setHasError(false);
    setIsLoading(false);
  };

  const confirmWithImpact = (target: GuardrailImpactRequest) => {
    setImpact(null);
    setRequest(target);
    void load(target);
  };

  const dialog = (
    <ImpactConfirmationDialog
      open={Boolean(request)}
      onOpenChange={(open) => {
        if (!open) close();
      }}
      title={request?.title ?? ""}
      description={request?.description ?? "Review the affected scopes before continuing."}
      confirmLabel={request?.confirmLabel ?? "Confirm"}
      isLoadingImpact={isLoading}
      impactError={hasError}
      onRetryImpact={request ? () => void load(request) : undefined}
      onConfirm={() => {
        request?.onConfirm();
        close();
      }}
    >
      {impact ? <GuardrailImpactPreview impact={impact} /> : null}
    </ImpactConfirmationDialog>
  );

  return { confirmWithImpact, dialog };
}

function GuardrailImpactPreview({ impact }: { impact: GuardrailImpactResponse }) {
  const affectedKeys = impact.affected_virtual_keys ?? [];
  return (
    <div className="grid gap-3 rounded-md border bg-muted/30 p-3 text-sm">
      <div className="grid grid-cols-3 gap-2">
        <ImpactCount label="Teams" value={impact.affected_team_count ?? 0} />
        <ImpactCount label="Projects" value={impact.affected_project_count ?? 0} />
        <ImpactCount label="Virtual keys" value={impact.affected_virtual_key_count ?? 0} />
      </div>
      {affectedKeys.length > 0 ? (
        <div className="text-xs text-muted-foreground">
          {affectedKeys
            .slice(0, 5)
            .map((key) => key.name)
            .join(", ")}
          {affectedKeys.length > 5 ? `, +${affectedKeys.length - 5} more` : ""}
        </div>
      ) : null}
    </div>
  );
}

function ImpactCount({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border bg-background p-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}

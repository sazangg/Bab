import { ImpactConfirmationDialog } from "@/shared/components/ImpactConfirmationDialog";
import type { ProviderResourceImpactResponse } from "@/shared/api/generated/schemas";

/**
 * Impact-gated "disable" confirmation for provider resources (credentials, pools, models).
 * Renders the provider-specific impact preview inside the shared ImpactConfirmationDialog.
 */
export function ResourceImpactDialog({
  open,
  title,
  impact,
  loading,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  title: string;
  impact: ProviderResourceImpactResponse | null;
  loading: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <ImpactConfirmationDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description="Review active routing and recent usage before continuing."
      confirmLabel="Disable"
      isLoadingImpact={loading}
      onConfirm={onConfirm}
    >
      {impact ? (
        <div className="space-y-2 text-sm">
          <p>
            {impact.active_pool_membership_count ?? 0} active pool memberships,{" "}
            {impact.access_policies?.length ?? 0} access routes, and{" "}
            {impact.active_limit_rule_count ?? 0} limit rules.
          </p>
          <p>
            Last 30 days: {(impact.recent_request_count ?? 0).toLocaleString()} requests and $
            {((impact.recent_cost_cents ?? 0) / 100).toFixed(2)} estimated spend.
          </p>
          {impact.leaves_provider_unroutable ? (
            <p className="font-medium text-destructive">
              This action removes the provider's last active resource of this type.
            </p>
          ) : null}
        </div>
      ) : null}
    </ImpactConfirmationDialog>
  );
}

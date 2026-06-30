export type ProviderReadinessStepId =
  | "enabled"
  | "credential"
  | "validated_credential"
  | "pool"
  | "pool_credential"
  | "model";

export type ProviderReadinessAction =
  | "enable_provider"
  | "add_credential"
  | "test_credentials"
  | "create_pool"
  | "attach_credential"
  | "sync_or_add_models"
  | "open_playground"
  | null;

export type ProviderReadinessInput = {
  providerEnabled: boolean;
  credentialCount: number;
  validatedCredentialCount: number;
  poolCount: number;
  poolsWithCredentialsCount: number;
  modelCount: number;
};

export type ProviderReadinessStep = {
  id: ProviderReadinessStepId;
  label: string;
  complete: boolean;
  action: ProviderReadinessAction;
};

export type ProviderReadiness = {
  steps: ProviderReadinessStep[];
  isReady: boolean;
  nextAction: ProviderReadinessAction;
};

export function getProviderReadiness(input: ProviderReadinessInput): ProviderReadiness {
  const steps: ProviderReadinessStep[] = [
    {
      id: "enabled",
      label: "Enable provider",
      complete: input.providerEnabled,
      action: "enable_provider",
    },
    {
      id: "credential",
      label: "Add credential",
      complete: input.credentialCount > 0,
      action: "add_credential",
    },
    {
      id: "validated_credential",
      label: "Validate credential",
      complete: input.validatedCredentialCount > 0,
      action: "test_credentials",
    },
    {
      id: "pool",
      label: "Create active pool",
      complete: input.poolCount > 0,
      action: "create_pool",
    },
    {
      id: "pool_credential",
      label: "Attach credential",
      complete: input.poolsWithCredentialsCount > 0,
      action: "attach_credential",
    },
    {
      id: "model",
      label: "Sync or add models",
      complete: input.modelCount > 0,
      action: "sync_or_add_models",
    },
  ];
  const nextIncomplete = steps.find((step) => !step.complete);

  return {
    steps,
    isReady: !nextIncomplete,
    nextAction: nextIncomplete?.action ?? "open_playground",
  };
}

export function providerReadinessActionLabel(action: ProviderReadinessAction) {
  const labels: Record<Exclude<ProviderReadinessAction, null>, string> = {
    enable_provider: "Enable provider",
    add_credential: "Add credential",
    test_credentials: "Test credentials",
    create_pool: "Create pool",
    attach_credential: "Configure pool",
    sync_or_add_models: "Add or sync models",
    open_playground: "Open playground",
  };
  return action ? labels[action] : null;
}

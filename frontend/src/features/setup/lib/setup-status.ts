export type SetupStepId =
  | "provider"
  | "provider_ready"
  | "team"
  | "project"
  | "virtual_key"
  | "first_request"
  | "policies";

export type SetupStatusInput = {
  providersCount: number;
  readyProvidersCount: number;
  teamsCount: number;
  projectsCount: number;
  usableVirtualKeysCount: number;
  gatewayRequestsCount: number;
  accessPoliciesCount: number;
  limitPoliciesCount: number;
  guardrailPoliciesCount: number;
};

export type SetupStepState = {
  id: SetupStepId;
  label: string;
  description: string;
  complete: boolean;
  optional?: boolean;
  to: string;
  actionLabel: string;
};

export type SetupStatus = {
  steps: SetupStepState[];
  requiredSteps: SetupStepState[];
  completedRequiredCount: number;
  totalRequiredCount: number;
  nextRequiredStep: SetupStepState | null;
  isComplete: boolean;
};

export function buildSetupStatus(input: SetupStatusInput): SetupStatus {
  const steps: SetupStepState[] = [
    {
      id: "provider",
      label: "Connect provider",
      description: "Add at least one provider so Bab can route model traffic.",
      complete: input.providersCount > 0,
      to: "/providers",
      actionLabel: "Open providers",
    },
    {
      id: "provider_ready",
      label: "Make provider routing-ready",
      description: "Configure credentials, pools, and model offerings until a provider is ready.",
      complete: input.readyProvidersCount > 0,
      to: "/providers",
      actionLabel: "Review provider setup",
    },
    {
      id: "team",
      label: "Create team",
      description: "Create a team to own projects and access boundaries.",
      complete: input.teamsCount > 0,
      to: "/teams",
      actionLabel: "Open teams",
    },
    {
      id: "project",
      label: "Create project",
      description: "Create a project under a team for keys and usage attribution.",
      complete: input.projectsCount > 0,
      to: "/projects",
      actionLabel: "Open projects",
    },
    {
      id: "virtual_key",
      label: "Create usable virtual key",
      description: "Issue a virtual key that can make gateway requests.",
      complete: input.usableVirtualKeysCount > 0,
      to: "/virtual-keys",
      actionLabel: "Open virtual keys",
    },
    {
      id: "first_request",
      label: "Send first gateway request",
      description: "Run a request through the gateway and confirm it appears in history.",
      complete: input.gatewayRequestsCount > 0,
      to: "/playground",
      actionLabel: "Open playground",
    },
    {
      id: "policies",
      label: "Configure policies or guardrails",
      description: "Optionally add access policies, limits, or safety guardrails.",
      complete:
        input.accessPoliciesCount + input.limitPoliciesCount + input.guardrailPoliciesCount > 0,
      optional: true,
      to: "/policies",
      actionLabel: "Open policies",
    },
  ];
  const requiredSteps = steps.filter((step) => !step.optional);
  const completedRequiredCount = requiredSteps.filter((step) => step.complete).length;
  const nextRequiredStep = requiredSteps.find((step) => !step.complete) ?? null;

  return {
    steps,
    requiredSteps,
    completedRequiredCount,
    totalRequiredCount: requiredSteps.length,
    nextRequiredStep,
    isComplete: completedRequiredCount === requiredSteps.length,
  };
}

import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useListAccessPoliciesApiV1PoliciesAccessGet,
} from "@/shared/api/generated/policies/policies";
import {
  useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet,
  useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet,
  useListProvidersApiV1ProvidersGet,
} from "@/shared/api/generated/providers/providers";
import type { LimitPolicyRuleResponse } from "@/shared/api/generated/schemas";

const ALL_VALUE = "__all__";

export type LimitRuleFilterValue = {
  providerId: string;
  poolId: string;
  modelId: string;
  accessPolicyId: string;
};

export function LimitRuleFilterFields({
  value,
  onChange,
}: {
  value: LimitRuleFilterValue;
  onChange: (value: LimitRuleFilterValue) => void;
}) {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(value.providerId, {
    query: { enabled: Boolean(value.providerId) },
  });
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(
    value.providerId,
    { limit: 1000 },
    { query: { enabled: Boolean(value.providerId) } },
  );
  const accessPoliciesQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data.items : [];
  const accessPolicies =
    accessPoliciesQuery.data?.status === 200 ? accessPoliciesQuery.data.data : [];

  const update = (changes: Partial<LimitRuleFilterValue>) =>
    onChange({
      ...value,
      ...changes,
    });

  return (
    <div className="grid gap-3 rounded-md border bg-background/70 p-3">
      <div>
        <div className="text-sm font-medium">Optional filters</div>
        <p className="text-xs text-muted-foreground">
          Leave filters unset to apply this rule to all matching traffic.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <FilterSelect
          label="Provider"
          value={value.providerId}
          emptyLabel="All providers"
          options={providers.map((provider) => ({
            value: provider.id,
            label: provider.display_name ?? provider.name,
          }))}
          onValueChange={(providerId) =>
            update({
              providerId,
              poolId: "",
              modelId: "",
            })
          }
        />
        <FilterSelect
          label="Credential pool"
          value={value.poolId}
          emptyLabel="All pools"
          disabled={!value.providerId}
          options={pools.map((pool) => ({ value: pool.id, label: pool.name }))}
          onValueChange={(poolId) => update({ poolId })}
        />
        <FilterSelect
          label="Model"
          value={value.modelId}
          emptyLabel="All models"
          disabled={!value.providerId}
          options={models.map((model) => ({
            value: model.id,
            label: model.provider_model_name,
          }))}
          onValueChange={(modelId) => update({ modelId })}
        />
        <FilterSelect
          label="Access policy"
          value={value.accessPolicyId}
          emptyLabel="Any access policy"
          options={accessPolicies.map((policy) => ({ value: policy.id, label: policy.name }))}
          onValueChange={(accessPolicyId) => update({ accessPolicyId })}
        />
      </div>
    </div>
  );
}

export function LimitRuleFiltersSummary({ rule }: { rule: LimitPolicyRuleResponse }) {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const poolsQuery = useListCredentialPoolsApiV1ProvidersProviderIdPoolsGet(
    rule.provider_id ?? "",
    { query: { enabled: Boolean(rule.provider_id) } },
  );
  const modelsQuery = useListModelOfferingsApiV1ProvidersProviderIdOfferingsGet(
    rule.provider_id ?? "",
    { limit: 1000 },
    { query: { enabled: Boolean(rule.provider_id) } },
  );
  const accessPoliciesQuery = useListAccessPoliciesApiV1PoliciesAccessGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const pools = poolsQuery.data?.status === 200 ? poolsQuery.data.data : [];
  const models = modelsQuery.data?.status === 200 ? modelsQuery.data.data.items : [];
  const accessPolicies =
    accessPoliciesQuery.data?.status === 200 ? accessPoliciesQuery.data.data : [];
  const filters = [
    rule.provider_id
      ? providers.find((provider) => provider.id === rule.provider_id)?.display_name ??
        providers.find((provider) => provider.id === rule.provider_id)?.name ??
        `Provider ${rule.provider_id.slice(0, 8)}`
      : null,
    rule.credential_pool_id
      ? pools.find((pool) => pool.id === rule.credential_pool_id)?.name ??
        `Pool ${rule.credential_pool_id.slice(0, 8)}`
      : null,
    rule.model_offering_id
      ? models.find((model) => model.id === rule.model_offering_id)?.provider_model_name ??
        `Model ${rule.model_offering_id.slice(0, 8)}`
      : null,
    rule.access_policy_id
      ? accessPolicies.find((policy) => policy.id === rule.access_policy_id)?.name ??
        `Access ${rule.access_policy_id.slice(0, 8)}`
      : null,
  ].filter(Boolean);
  return <>{filters.length ? filters.join(" · ") : "All matching traffic"}</>;
}

function FilterSelect({
  label,
  value,
  emptyLabel,
  options,
  disabled = false,
  onValueChange,
}: {
  label: string;
  value: string;
  emptyLabel: string;
  options: { value: string; label: string }[];
  disabled?: boolean;
  onValueChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      <Select
        value={value || ALL_VALUE}
        onValueChange={(nextValue) => onValueChange(nextValue === ALL_VALUE ? "" : nextValue)}
        disabled={disabled}
      >
        <SelectTrigger>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_VALUE}>{emptyLabel}</SelectItem>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              <span className="block max-w-[28rem] truncate">{option.label}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

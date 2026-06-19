import type { UseFormRegister } from "react-hook-form";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ProviderModelOfferingResponse } from "@/shared/api/generated/schemas";

import { formatPricingSource, formatTokenPrice } from "../../lib/format";
import { modelCapabilityOptions, modelModalities, type ModelOfferingFormInput } from "../../lib/schemas";

export function PricingFields({
  register,
  prefix,
}: {
  register: UseFormRegister<ModelOfferingFormInput>;
  prefix: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label>Pricing (USD per 1M tokens)</Label>
      <p className="text-xs text-muted-foreground">
        Enter dollars. Bab stores normalized cents for usage and budget calculations.
      </p>
      <div className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1.5">
          <Label htmlFor={`${prefix}-provider-model-input-price`} className="text-xs text-muted-foreground">
            Input
          </Label>
          <Input
            id={`${prefix}-provider-model-input-price`}
            type="number"
            min={0}
            step="0.0001"
            placeholder="0"
            {...register("input_price_per_million_tokens")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${prefix}-provider-model-output-price`} className="text-xs text-muted-foreground">
            Output
          </Label>
          <Input
            id={`${prefix}-provider-model-output-price`}
            type="number"
            min={0}
            step="0.0001"
            placeholder="0"
            {...register("output_price_per_million_tokens")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${prefix}-provider-model-cached-price`} className="text-xs text-muted-foreground">
            Cached input
          </Label>
          <Input
            id={`${prefix}-provider-model-cached-price`}
            type="number"
            min={0}
            step="0.0001"
            placeholder="0"
            {...register("cached_input_price_per_million_tokens")}
          />
        </div>
      </div>
    </div>
  );
}

export function PricingSnapshot({ model }: { model: ProviderModelOfferingResponse }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3 text-sm">
      <div className="font-medium">Effective pricing</div>
      <div className="mt-2 grid gap-2 text-xs sm:grid-cols-3">
        <Fact label="Input" value={formatTokenPrice(model.effective_input_price_per_million_tokens)} />
        <Fact label="Output" value={formatTokenPrice(model.effective_output_price_per_million_tokens)} />
        <Fact
          label="Cached input"
          value={formatTokenPrice(model.effective_cached_input_price_per_million_tokens)}
        />
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        {formatPricingSource(model.pricing_source)}
      </div>
    </div>
  );
}

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-muted-foreground">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}

export function ModalityCheckboxGroup({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>{label}</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {modelModalities.map((item) => (
          <CheckboxOption
            key={item}
            label={item}
            checked={values.includes(item)}
            onCheckedChange={(checked) => {
              const next = checked ? [...values, item] : values.filter((value) => value !== item);
              onChange(next.length ? next : ["text"]);
            }}
          />
        ))}
      </div>
    </div>
  );
}

export function CapabilityCheckboxGroup({
  values,
  onChange,
}: {
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="flex flex-col gap-2">
      <Label>Capabilities</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {modelCapabilityOptions.map((item) => (
          <CheckboxOption
            key={item}
            label={item}
            checked={values.includes(item)}
            onCheckedChange={(checked) => {
              const next = checked ? [...values, item] : values.filter((value) => value !== item);
              onChange(next);
            }}
          />
        ))}
      </div>
    </div>
  );
}

function CheckboxOption({
  label,
  checked,
  onCheckedChange,
}: {
  label: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-md border p-2 text-sm">
      <Checkbox checked={checked} onCheckedChange={(value) => onCheckedChange(value === true)} />
      <span>{label}</span>
    </label>
  );
}

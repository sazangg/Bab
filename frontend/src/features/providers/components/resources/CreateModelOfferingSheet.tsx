import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
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

import {
  modelOfferingSchema,
  type ModelOfferingFormInput,
  type ModelOfferingValues,
} from "../../lib/schemas";
import {
  CapabilityCheckboxGroup,
  ModalityCheckboxGroup,
  PricingFields,
} from "./ModelFormFields";

const defaultModelValues: ModelOfferingFormInput = {
  provider_model_name: "",
  alias: "",
  version: "",
  input_modalities: ["text"],
  output_modalities: ["text"],
  context_window: undefined,
  input_price_per_million_tokens: undefined,
  output_price_per_million_tokens: undefined,
  cached_input_price_per_million_tokens: undefined,
  capabilities: ["chat", "streaming"],
};

export function CreateModelOfferingSheet({
  open,
  onOpenChange,
  providerName,
  onSubmit,
  isPending,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  providerName: string;
  onSubmit: (values: ModelOfferingValues) => void;
  isPending: boolean;
}) {
  const form = useForm<ModelOfferingFormInput, unknown, ModelOfferingValues>({
    resolver: zodResolver(modelOfferingSchema),
    defaultValues: defaultModelValues,
  });
  const inputModalities = useWatch({ control: form.control, name: "input_modalities" });
  const outputModalities = useWatch({ control: form.control, name: "output_modalities" });
  const capabilities = useWatch({ control: form.control, name: "capabilities" });

  useEffect(() => {
    if (open) {
      form.reset(defaultModelValues);
    }
  }, [open, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>Add model</SheetTitle>
          <SheetDescription>
            Register a model exposed by {providerName}. Alias is optional and provider-scoped.
          </SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 overflow-y-auto px-6 py-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-name">Provider model name</Label>
            <Input
              id="detail-provider-model-name"
              autoFocus
              placeholder="gpt-5.4-mini"
              {...form.register("provider_model_name")}
            />
            {form.formState.errors.provider_model_name ? (
              <p className="text-xs text-destructive">
                {form.formState.errors.provider_model_name.message}
              </p>
            ) : null}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-alias">Alias</Label>
            <Input id="detail-provider-model-alias" placeholder="fast" {...form.register("alias")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-version">Version</Label>
            <Input
              id="detail-provider-model-version"
              placeholder="2025-08-07"
              {...form.register("version")}
            />
          </div>
          <ModalityCheckboxGroup
            label="Input modalities"
            values={inputModalities ?? []}
            onChange={(values) => form.setValue("input_modalities", values)}
          />
          <ModalityCheckboxGroup
            label="Output modalities"
            values={outputModalities ?? []}
            onChange={(values) => form.setValue("output_modalities", values)}
          />
          <div className="space-y-1.5">
            <Label htmlFor="detail-provider-model-context">Context window</Label>
            <Input
              id="detail-provider-model-context"
              type="number"
              min={1}
              placeholder="128000"
              {...form.register("context_window")}
            />
            {form.formState.errors.context_window ? (
              <p className="text-xs text-destructive">
                {form.formState.errors.context_window.message}
              </p>
            ) : null}
          </div>
          <PricingFields register={form.register} prefix="detail" />
          <CapabilityCheckboxGroup
            values={capabilities ?? []}
            onChange={(values) => form.setValue("capabilities", values)}
          />
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Adding..." : "Add model"}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

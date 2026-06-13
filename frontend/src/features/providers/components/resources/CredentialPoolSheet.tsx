import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import type { CredentialPoolResponse } from "@/shared/api/generated/schemas";

import { credentialPoolSchema, routingPolicyOptions, type CredentialPoolValues } from "../../lib/schemas";
import { toRoutingPolicyValue } from "../../lib/resources-helpers";

export function CredentialPoolSheet({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  initialValue,
  isPending,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  submitLabel: string;
  initialValue?: CredentialPoolResponse | null;
  isPending?: boolean;
  onSubmit: (values: CredentialPoolValues) => void;
}) {
  const form = useForm<CredentialPoolValues>({
    resolver: zodResolver(credentialPoolSchema),
    defaultValues: { name: "", description: "", selection_policy: "priority" },
  });
  const selectedPolicy = useWatch({ control: form.control, name: "selection_policy" });

  useEffect(() => {
    if (!open) return;
    form.reset({
      name: initialValue?.name ?? "",
      description: initialValue?.description ?? "",
      selection_policy: toRoutingPolicyValue(initialValue?.selection_policy ?? "priority"),
    });
  }, [open, initialValue, form]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          <SheetDescription>{description}</SheetDescription>
        </SheetHeader>
        <form className="grid gap-4 overflow-y-auto px-6 py-5" onSubmit={form.handleSubmit(onSubmit)}>
          <div className="space-y-1.5">
            <Label htmlFor="credential-pool-name">Name</Label>
            <Input id="credential-pool-name" autoFocus {...form.register("name")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="credential-pool-description">Description</Label>
            <Textarea id="credential-pool-description" {...form.register("description")} />
          </div>
          <div className="space-y-1.5">
            <Label>Selection policy</Label>
            <Select
              value={selectedPolicy}
              onValueChange={(value) =>
                form.setValue("selection_policy", value as CredentialPoolValues["selection_policy"])
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {routingPolicyOptions.map((option) => (
                  <SelectItem key={option.value} value={option.value}>
                    {option.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {routingPolicyOptions.find((option) => option.value === selectedPolicy)?.description}
            </p>
          </div>
        </form>
        <SheetFooter>
          <Button disabled={isPending} onClick={form.handleSubmit(onSubmit)}>
            {isPending ? "Saving..." : submitLabel}
          </Button>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

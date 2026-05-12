import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Layers3, Plus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  useGrantProjectSubscriptionAccessApiV1ProjectsProjectIdSubscriptionAccessPost,
} from "@/shared/api/generated/projects/projects";
import type {
  ProjectSubscriptionAccessResponse,
  SubscriptionResponse,
} from "@/shared/api/generated/schemas";
import { EmptyState } from "@/shared/components/EmptyState";
import { StatusBadge } from "@/shared/components/StatusBadge";

const grantSchema = z.object({
  subscription_id: z.string().min(1, "Pick a subscription"),
  priority: z.number().int().min(0),
});

type GrantValues = z.infer<typeof grantSchema>;

export function ProjectAccessSection({
  projectId,
  subscriptions,
  accessRules,
  isLoading,
}: {
  projectId: string;
  subscriptions: SubscriptionResponse[];
  accessRules: ProjectSubscriptionAccessResponse[];
  isLoading: boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const grantedSubscriptionIds = new Set(accessRules.map((rule) => rule.subscription_id));
  const availableSubscriptions = subscriptions.filter(
    (subscription) => subscription.is_active && !grantedSubscriptionIds.has(subscription.id),
  );

  const form = useForm<GrantValues>({
    resolver: zodResolver(grantSchema),
    defaultValues: { subscription_id: "", priority: 100 },
  });
  const subscriptionId = useWatch({ control: form.control, name: "subscription_id" });
  const grantMutation = useGrantProjectSubscriptionAccessApiV1ProjectsProjectIdSubscriptionAccessPost({
    mutation: {
      onSuccess: async () => {
        form.reset({ subscription_id: "", priority: 100 });
        setOpen(false);
        await queryClient.invalidateQueries();
      },
    },
  });

  const submit = form.handleSubmit((values) =>
    grantMutation.mutate({
      projectId,
      data: { subscription_id: values.subscription_id, priority: values.priority },
    }),
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Subscription access</CardTitle>
            <CardDescription>
              Projects inherit providers, provider keys, and models through subscriptions.
            </CardDescription>
          </div>
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button size="sm" disabled={availableSubscriptions.length === 0}>
                <Plus />
                Attach subscription
              </Button>
            </SheetTrigger>
            <SheetContent>
              <SheetHeader>
                <SheetTitle>Attach subscription</SheetTitle>
                <SheetDescription>
                  Lower priority wins when the same alias exists across subscriptions.
                </SheetDescription>
              </SheetHeader>
              <form className="grid gap-4 px-4" onSubmit={submit}>
                <div className="space-y-1.5">
                  <Label>Subscription</Label>
                  <Select
                    value={subscriptionId}
                    onValueChange={(value) => form.setValue("subscription_id", value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="Select subscription" />
                    </SelectTrigger>
                    <SelectContent>
                      {availableSubscriptions.map((subscription) => (
                        <SelectItem key={subscription.id} value={subscription.id}>
                          {subscription.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="subscription-priority">Priority</Label>
                  <Input
                    id="subscription-priority"
                    type="number"
                    {...form.register("priority", { valueAsNumber: true })}
                  />
                </div>
              </form>
              <SheetFooter>
                <Button disabled={grantMutation.isPending} onClick={submit}>
                  {grantMutation.isPending ? "Attaching..." : "Attach"}
                </Button>
                <SheetClose asChild>
                  <Button variant="outline">Cancel</Button>
                </SheetClose>
              </SheetFooter>
            </SheetContent>
          </Sheet>
        </div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <p className="text-sm text-muted-foreground">Loading subscription access...</p>
        ) : accessRules.length === 0 ? (
          <EmptyState
            icon={Layers3}
            title="No subscriptions attached"
            description="Attach a subscription before issuing keys for this project."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Subscription</TableHead>
                <TableHead>Priority</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {accessRules.map((rule) => {
                const subscription = subscriptions.find((item) => item.id === rule.subscription_id);
                return (
                  <TableRow key={rule.id}>
                    <TableCell className="font-medium">
                      {subscription?.name ?? rule.subscription_id}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{rule.priority}</TableCell>
                    <TableCell>
                      <StatusBadge variant={rule.is_active ? "active" : "inactive"}>
                        {rule.is_active ? "Active" : "Disabled"}
                      </StatusBadge>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

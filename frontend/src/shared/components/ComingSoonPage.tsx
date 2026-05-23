import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/shared/components/PageHeader";

export function ComingSoonPage({
  title,
  description,
  icon: Icon,
  outcomes,
}: {
  title: string;
  description: string;
  icon: LucideIcon;
  outcomes: string[];
}) {
  return (
    <div className="space-y-6">
      <PageHeader title={title} description={description} />
      <Card>
        <CardHeader className="border-b">
          <div className="flex items-center justify-between gap-3">
            <CardTitle>Planned surface</CardTitle>
            <Badge variant="outline">Not implemented</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-[14rem_1fr]">
            <div className="flex min-h-36 items-center justify-center rounded-lg border bg-muted/30">
              <Icon className="size-8 text-muted-foreground" />
            </div>
            <div className="grid gap-2">
              {outcomes.map((outcome) => (
                <div key={outcome} className="rounded-lg border bg-background p-3 text-sm">
                  {outcome}
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

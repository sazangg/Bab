import { ArrowRight, KeyRound, Plug } from "lucide-react";
import { Link } from "react-router-dom";

import { useListProvidersApiV1ProvidersGet } from "@/shared/api/generated/providers/providers";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function OverviewPage() {
  const providersQuery = useListProvidersApiV1ProvidersGet();
  const providers = providersQuery.data?.status === 200 ? providersQuery.data.data : [];
  const activeProviders = providers.filter((provider) => provider.is_active);

  return (
    <div className="min-h-[calc(100vh-8rem)] rounded-lg bg-black p-6 text-white">
      <div className="mx-auto flex max-w-5xl flex-col gap-8">
        <header className="flex flex-col gap-4 border-b border-white/10 pb-8">
          <div className="flex size-11 items-center justify-center rounded-md bg-white text-black">
            <KeyRound className="size-5" />
          </div>
          <div className="space-y-2">
            <p className="text-sm text-white/55">Default Organization / Default Team</p>
            <h1 className="max-w-3xl text-3xl font-semibold tracking-normal text-white">
              Bab is running with mock admin access.
            </h1>
            <p className="max-w-2xl text-sm leading-6 text-white/60">
              The current slice is intentionally narrow: connect OpenAI-compatible
              provider keys, verify that the management flow works, then bring back the
              next product surface vertically.
            </p>
          </div>
        </header>

        <div className="grid gap-4 md:grid-cols-3">
          <SummaryCard label="Providers" value={providers.length} />
          <SummaryCard label="Active providers" value={activeProviders.length} />
          <SummaryCard
            label="Current focus"
            value={providers.length > 0 ? "Keys" : "Onboarding"}
            textValue
          />
        </div>

        <Card className="border-white/10 bg-white/[0.03] text-white">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Plug className="size-4" />
              Provider key management
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <p className="max-w-2xl text-sm leading-6 text-white/60">
              Add a key to a known provider or create a custom OpenAI-compatible provider.
              Other dashboard areas stay hidden until their backend and frontend flows are
              ready to test as complete vertical slices.
            </p>
            <Button asChild variant="secondary">
              <Link to="/providers">
                Manage provider keys
                <ArrowRight className="size-4" />
              </Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  textValue = false,
}: {
  label: string;
  value: number | string;
  textValue?: boolean;
}) {
  return (
    <Card className="border-white/10 bg-white/[0.03] text-white">
      <CardHeader>
        <p className="text-sm text-white/50">{label}</p>
        <CardTitle className={textValue ? "text-2xl" : "text-3xl tabular-nums"}>
          {value}
        </CardTitle>
      </CardHeader>
    </Card>
  );
}

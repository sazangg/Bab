import { Activity, KeyRound, ServerCog } from "lucide-react";

const dashboardSections = [
  {
    title: "Providers",
    description: "Connect OpenAI-compatible upstream providers.",
    icon: ServerCog,
  },
  {
    title: "Projects",
    description: "Group keys and provider access by application.",
    icon: Activity,
  },
  {
    title: "Virtual keys",
    description: "Issue scoped keys for apps that call Bab.",
    icon: KeyRound,
  },
];

export function DashboardHomePage() {
  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-medium text-muted-foreground">Overview</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-normal">Bab control plane</h1>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {dashboardSections.map((section) => {
          const Icon = section.icon;

          return (
            <section
              key={section.title}
              className="rounded-lg border bg-card p-4 text-card-foreground"
            >
              <Icon className="size-5 text-muted-foreground" aria-hidden="true" />
              <h2 className="mt-4 text-sm font-semibold">{section.title}</h2>
              <p className="mt-1 text-sm leading-6 text-muted-foreground">{section.description}</p>
            </section>
          );
        })}
      </div>
    </div>
  );
}

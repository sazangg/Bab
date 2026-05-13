export function OverviewPage() {
  return (
    <section className="max-w-3xl space-y-3">
      <h1 className="text-3xl font-semibold tracking-normal">Bab</h1>
      <p className="text-muted-foreground">
        Bab is a self-hosted LLM gateway for centralizing provider API keys,
        exposing OpenAI-compatible access to downstream projects, and giving admins a
        clear place to manage provider access, usage, limits, and governance as the
        product grows.
      </p>
    </section>
  );
}

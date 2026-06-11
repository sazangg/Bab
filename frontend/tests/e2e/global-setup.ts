async function waitForBackend(url: string) {
  const deadline = Date.now() + 30_000;
  let lastError: unknown;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${url}/api/v1/health`);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error(
    `Backend is unavailable at ${url}. Start it separately or let Playwright webServer start it. Last error: ${String(lastError)}`,
  );
}

export default async function globalSetup() {
  const backendURL = process.env.E2E_BACKEND_URL ?? "http://127.0.0.1:8011";
  await waitForBackend(backendURL);
}

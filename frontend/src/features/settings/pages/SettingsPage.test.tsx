import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "./SettingsPage";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal("ResizeObserver", ResizeObserverStub);

const settingsHook = vi.hoisted(() => vi.fn());
const meHook = vi.hoisted(() => vi.fn());
const updateHook = vi.hoisted(() => vi.fn());
const uploadHook = vi.hoisted(() => vi.fn());

vi.mock("@/shared/api/generated/settings/settings", () => ({
  useGetSettingsApiV1SettingsGet: settingsHook,
  useUpdateSettingsApiV1SettingsPatch: updateHook,
  useUploadOrganizationLogoApiV1SettingsOrganizationLogoPost: uploadHook,
}));

vi.mock("@/shared/api/generated/auth/auth", () => ({
  useMeApiV1AuthMeGet: meHook,
}));

const settings = {
  id: "settings-id",
  org_id: "org-id",
  organization_name: "Bab",
  organization_logo_url: null,
  public_app_url: null,
  public_base_url: null,
  default_request_timeout_seconds: 30,
  default_retry_count: 0,
  default_max_body_bytes: 1_000_000,
  deployment_max_body_bytes: 2_000_000,
  default_model_sync_mode: "merge",
  default_virtual_key_expiration_days: null,
  usage_retention_days: null,
  activity_retention_days: 30,
  virtual_key_prefix: "bab",
  allow_secret_copy: true,
  created_at: "2026-06-12T00:00:00Z",
  updated_at: "2026-06-12T00:00:00Z",
};

describe("SettingsPage", () => {
  beforeEach(() => {
    settingsHook.mockReturnValue({ data: { status: 200, data: settings }, isPending: false });
    meHook.mockReturnValue({
      data: { status: 200, data: { role: "org_owner", permissions: ["settings.manage"] } },
    });
    updateHook.mockReturnValue({ mutate: vi.fn(), isPending: false });
    uploadHook.mockReturnValue({ mutate: vi.fn(), isPending: false });
  });

  it("shows deployment-owned retention and enables save only for valid dirty values", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    const save = screen.getByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    expect(screen.getByText("Deployment usage retention intent")).toBeInTheDocument();
    expect(screen.getByText("Deployment activity retention intent")).toBeInTheDocument();

    const appUrl = screen.getByLabelText("Public app URL");
    await user.type(appUrl, "not-a-url");
    expect(save).toBeEnabled();
    await user.click(save);

    expect(
      await screen.findByText("Enter an absolute http:// or https:// app URL."),
    ).toBeInTheDocument();
  });
});

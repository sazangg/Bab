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
const updateMutate = vi.hoisted(() => vi.fn());

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
    updateMutate.mockReset();
    updateHook.mockReturnValue({ mutate: updateMutate, isPending: false });
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
    expect(
      await screen.findByText("Enter an absolute http:// or https:// app URL."),
    ).toBeInTheDocument();
    expect(save).toBeDisabled();
  });

  it("blocks values above the deployment ceiling and discards dirty values", async () => {
    const user = userEvent.setup();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    const bodySize = screen.getByLabelText("Max body bytes");
    await user.clear(bodySize);
    await user.type(bodySize, "3000000");
    expect(
      await screen.findByText("Must not exceed the deployment ceiling of 2,000,000 bytes."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
    expect(updateMutate).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(bodySize).toHaveValue(1_000_000);
  });

  it("explains read-only access and hides save actions", () => {
    meHook.mockReturnValue({
      data: { status: 200, data: { role: "org_viewer", permissions: [] } },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SettingsPage />
      </QueryClientProvider>,
    );

    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save settings" })).not.toBeInTheDocument();
  });
});

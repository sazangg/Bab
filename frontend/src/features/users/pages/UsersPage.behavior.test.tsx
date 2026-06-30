import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UsersPage } from "./UsersPage";

const createInviteHook = vi.hoisted(() => vi.fn());
const updateStatusHook = vi.hoisted(() => vi.fn());
const revokeInviteHook = vi.hoisted(() => vi.fn());
const inviteMutate = vi.hoisted(() => vi.fn());
const statusMutate = vi.hoisted(() => vi.fn());
const revokeMutate = vi.hoisted(() => vi.fn());
const inviteState = vi.hoisted(() => ({ options: null as any }));

vi.mock("@/shared/api/generated/auth/auth", () => ({
  useMeApiV1AuthMeGet: () => ({
    data: {
      status: 200,
      data: {
        id: "current-user",
        role: "org_owner",
        permissions: ["members.manage"],
        team_memberships: [],
        project_memberships: [],
      },
    },
  }),
  useListMembersApiV1AuthMembersGet: () => query([member()]),
  useListInvitesApiV1AuthInvitesGet: () => query([invite()]),
  useCreateInviteApiV1AuthInvitesPost: createInviteHook,
  useCreateMemberApiV1AuthMembersPost: () => mutation(),
  useUpdateMemberApiV1AuthMembersUserIdPatch: () => mutation(),
  useUpdateMemberStatusApiV1AuthMembersUserIdStatusPatch: updateStatusHook,
  useRevokeInviteApiV1AuthInvitesInviteIdDelete: revokeInviteHook,
}));

vi.mock("@/shared/api/generated/teams/teams", () => ({
  useListTeamsApiV1TeamsGet: () => query([]),
}));

vi.mock("@/shared/api/generated/projects/projects", () => ({
  useListProjectsApiV1ProjectsGet: () => query([]),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("UsersPage behavior", () => {
  beforeEach(() => {
    inviteMutate.mockReset();
    statusMutate.mockReset();
    revokeMutate.mockReset();
    createInviteHook.mockImplementation((options) => {
      inviteState.options = options;
      return { mutate: inviteMutate, isPending: false };
    });
    updateStatusHook.mockReturnValue({ mutate: statusMutate, isPending: false });
    revokeInviteHook.mockReturnValue({ mutate: revokeMutate, isPending: false });
  });

  it("preserves invite input after a failed submission", async () => {
    const user = userEvent.setup();
    renderPage();

    const email = screen.getByLabelText("Email");
    await user.type(email, "teammate@example.com");
    await user.click(screen.getByRole("button", { name: "Invite user" }));
    inviteState.options.mutation.onError(new Error("failed"));

    expect(email).toHaveValue("teammate@example.com");
  });

  it("confirms member deactivation before mutating", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Deactivate user" }));
    expect(statusMutate).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Deactivate user" }),
    );
    expect(statusMutate).toHaveBeenCalledTimes(1);
  });

  it("confirms invite revocation before mutating", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole("button", { name: "Revoke invite" }));
    expect(revokeMutate).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Revoke invite" }),
    );
    expect(revokeMutate).toHaveBeenCalledTimes(1);
  });
});

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <UsersPage />
    </QueryClientProvider>,
  );
}

function query(data: unknown[]) {
  return {
    data: { status: 200, data },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  };
}

function mutation() {
  return { mutate: vi.fn(), isPending: false };
}

function member() {
  return {
    user_id: "member-1",
    email: "member@example.com",
    name: "Member",
    role: "org_member",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    team_memberships: [],
    project_memberships: [],
    permissions: [],
  };
}

function invite() {
  return {
    id: "invite-1",
    email: "invite@example.com",
    role: "org_member",
    status: "pending",
    invite_url: "/invite/token",
    team_id: null,
    team_role: null,
    project_id: null,
    project_role: null,
    expires_at: "2026-07-01T00:00:00Z",
  };
}

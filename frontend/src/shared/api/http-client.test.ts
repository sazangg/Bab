import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/features/auth/model/auth-store";
import { getAccessToken } from "@/shared/auth/access-token-store";
import { refreshAccessToken, refreshClient } from "@/shared/api/http-client";

describe("refreshAccessToken", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAuthStore.getState().clearSession();
  });

  it("shares one refresh request across concurrent callers", async () => {
    const post = vi
      .spyOn(refreshClient, "post")
      .mockResolvedValue({ data: { access_token: "fresh-token" } });

    const [first, second] = await Promise.all([refreshAccessToken(), refreshAccessToken()]);

    expect(post).toHaveBeenCalledTimes(1);
    expect(first).toBe("fresh-token");
    expect(second).toBe("fresh-token");
    expect(getAccessToken()).toBe("fresh-token");
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });

  it("clears the complete session when refresh fails", async () => {
    useAuthStore.getState().setSession("expired-token");
    vi.spyOn(refreshClient, "post").mockRejectedValue(new Error("refresh failed"));

    await expect(refreshAccessToken()).rejects.toThrow("refresh failed");

    expect(getAccessToken()).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
  });
});

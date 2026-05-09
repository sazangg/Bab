import { create } from "zustand";

import { setAccessToken } from "@/shared/auth/access-token-store";

type AuthState = {
  isAuthenticated: boolean;
  setSession: (accessToken: string) => void;
  clearSession: () => void;
};

export const useAuthStore = create<AuthState>((set) => ({
  isAuthenticated: false,
  setSession: (accessToken) => {
    setAccessToken(accessToken);
    set({ isAuthenticated: true });
  },
  clearSession: () => {
    setAccessToken(null);
    set({ isAuthenticated: false });
  },
}));

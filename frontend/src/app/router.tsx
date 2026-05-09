import { Navigate, Route, Routes } from "react-router-dom";

import { AuthLayout } from "@/app/shell/AuthLayout";
import { DashboardLayout } from "@/app/shell/DashboardLayout";
import { LoginPage } from "@/features/auth/pages/LoginPage";
import { DashboardHomePage } from "@/features/dashboard/pages/DashboardHomePage";
import { SetupPage } from "@/features/setup/pages/SetupPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AuthLayout />}>
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/login" element={<LoginPage />} />
      </Route>
      <Route element={<DashboardLayout />}>
        <Route path="/" element={<DashboardHomePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

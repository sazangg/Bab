import { Navigate, Route, Routes } from "react-router-dom";

import { LoginPage } from "./features/auth/pages/LoginPage";
import { SetupPage } from "./features/setup/pages/SetupPage";

export default function App() {
  return (
    <Routes>
      <Route path="/setup" element={<SetupPage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}

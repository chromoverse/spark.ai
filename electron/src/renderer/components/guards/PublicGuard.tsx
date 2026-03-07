import { useAppSelector } from "@/store/hooks";
import { Navigate, Outlet, useLocation } from "react-router-dom";

export default function PublicGuard() {
  const location = useLocation();
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  if (isAuthenticated && location.pathname !== "/auth/onboarding") {
    return <Navigate to="/home" replace />;
  }

  return <Outlet />;
}

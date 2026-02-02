import { useAppSelector } from "@/store/hooks";
import { Navigate, Outlet } from "react-router-dom";

export default function AuthGuard() {
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  if (!isAuthenticated) {
    return <Navigate to="/welcome" replace />;
  }

  return <Outlet />;
}

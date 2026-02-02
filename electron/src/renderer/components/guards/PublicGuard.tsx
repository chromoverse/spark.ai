import { useAppSelector } from "@/store/hooks";
import { Navigate, Outlet } from "react-router-dom";

export default function PublicGuard() {
  const { isAuthenticated } = useAppSelector((state) => state.auth);

  if (isAuthenticated) {
    return <Navigate to="/home" replace />;
  }

  return <Outlet />;
}

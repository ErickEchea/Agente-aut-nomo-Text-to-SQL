import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Navigate, Outlet, useLocation, useRouteError } from "react-router";

import { Logo } from "../components/Logo";
import { Button } from "../components/ui/button";
import { Spinner } from "../components/ui/primitives";
import { WorkspaceProvider } from "../features/workspace/session";
import { useAuth, useCan } from "./auth";

export function RequireAuth() {
  const { t } = useTranslation();
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-bg">
        <Logo />
        <Spinner label={t("common.loading")} className="text-accent" />
      </div>
    );
  }
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return (
    <WorkspaceProvider>
      <Outlet />
    </WorkspaceProvider>
  );
}

export function RequireAdmin() {
  const { admin } = useCan();
  return admin ? <Outlet /> : <Navigate to="/" replace />;
}

export function RouteError() {
  const { t } = useTranslation();
  const error = useRouteError();
  return (
    <div role="alert" className="flex min-h-[60vh] flex-col items-center justify-center gap-3 p-6 text-center">
      <TriangleAlert aria-hidden="true" className="size-8 text-danger" />
      <p className="text-h2 text-fg">{t("errors.boundary")}</p>
      <p className="max-w-md text-small text-fg-muted">{error instanceof Error ? error.message : t("errors.unknown")}</p>
      <Button
        variant="primary"
        onClick={() => {
          window.location.reload();
        }}
      >
        {t("common.retry")}
      </Button>
    </div>
  );
}

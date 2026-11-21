import type { TFunction } from "i18next";

import { ApiError, NetworkError } from "../api/client";
import { SseHttpError } from "./sse";

/** A human, actionable message for any error the UI can meet. */
export function errorMessage(error: unknown, t: TFunction): string {
  if (error instanceof NetworkError) return t("errors.network");
  const status =
    error instanceof ApiError ? error.status : error instanceof SseHttpError ? error.status : null;
  if (status === null) return error instanceof TypeError ? t("errors.network") : t("errors.unknown");
  if (status === 401) return t("errors.unauthorized");
  if (status === 403) return t("errors.forbidden");
  if (status === 404) return t("errors.notFound");
  if (status === 409) return t("errors.conflict");
  if (status === 422) return t("errors.validation");
  if (status === 429) {
    const seconds = error instanceof ApiError && error.retryAfterS ? error.retryAfterS : 30;
    return t("errors.rateLimited", { seconds });
  }
  if (status >= 500) return t("errors.server");
  return t("errors.unknown");
}

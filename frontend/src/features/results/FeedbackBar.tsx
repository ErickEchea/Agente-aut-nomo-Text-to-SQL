import { useMutation } from "@tanstack/react-query";
import { BadgeCheck, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import { useApi, useCan } from "../../app/auth";
import { Button } from "../../components/ui/button";
import { Tooltip } from "../../components/ui/overlays";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";

export function FeedbackBar({ runId, answered }: { runId: string; answered: boolean }) {
  const { t } = useTranslation();
  const api = useApi();
  const { contribute } = useCan();
  const [rating, setRating] = useState<"up" | "down" | null>(null);
  const [verified, setVerified] = useState(false);

  const mutation = useMutation({
    mutationFn: (body: { rating: "up" | "down"; verify?: boolean }) => endpoints.sendFeedback(api, runId, body),
    onSuccess: (result, body) => {
      setRating(body.rating);
      if (body.verify) {
        setVerified(true);
        toast.success(result.verified_examples > 0 ? t("feedback.verified") : t("feedback.alreadyVerified"));
      } else {
        toast.success(t("feedback.thanks"));
      }
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });

  if (!contribute) return null;

  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="mr-1 text-small text-fg-muted">{t("feedback.question")}</span>
      {(["up", "down"] as const).map((value) => {
        const Icon = value === "up" ? ThumbsUp : ThumbsDown;
        return (
          <Button
            key={value}
            variant="ghost"
            size="icon-sm"
            aria-label={t(`feedback.${value}`)}
            aria-pressed={rating === value}
            disabled={mutation.isPending}
            className={cn(rating === value && (value === "up" ? "text-success" : "text-danger"))}
            onClick={() => {
              mutation.mutate({ rating: value });
            }}
          >
            <Icon />
          </Button>
        );
      })}
      {answered ? (
        <Tooltip content={t("feedback.verifyHint")}>
          <Button
            variant="ghost"
            size="sm"
            disabled={mutation.isPending || verified}
            className={cn(verified && "text-success")}
            onClick={() => {
              mutation.mutate({ rating: "up", verify: true });
            }}
          >
            <BadgeCheck />
            {t("feedback.verify")}
          </Button>
        </Tooltip>
      ) : null}
    </div>
  );
}

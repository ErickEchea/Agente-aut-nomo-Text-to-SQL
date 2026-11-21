import { ArrowUp, MessageSquarePlus, Square } from "lucide-react";
import { useEffect, useId, useRef, useState, type SyntheticEvent, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "../../components/ui/button";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";
import { useWorkspace } from "./session";

export const QUESTION_INPUT_ID = "nexus-question";
const MIN = 3;
const MAX = 1000;

export function QueryBar({ runningRunId }: { runningRunId: string | null }) {
  const { t } = useTranslation();
  const { ask, cancel, busy, turns, newConversation } = useWorkspace();
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const area = useRef<HTMLTextAreaElement>(null);
  const hintId = useId();

  // Grow with the content up to ~6 lines.
  useEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 168)}px`;
  }, [question]);

  const trimmed = question.trim();
  const canSend = trimmed.length >= MIN && !busy && !sending;

  const submit = async (event?: SyntheticEvent) => {
    event?.preventDefault();
    if (!canSend) return;
    setSending(true);
    try {
      await ask(trimmed);
      setQuestion("");
    } catch (error) {
      toast.error(errorMessage(error, t));
    } finally {
      setSending(false);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void submit();
    }
  };

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="rounded-xl border border-line-strong bg-surface-1 p-2 shadow-overlay transition-colors focus-within:border-accent/70"
    >
      <label htmlFor={QUESTION_INPUT_ID} className="sr-only">
        {t("workspace.questionLabel")}
      </label>
      <textarea
        ref={area}
        id={QUESTION_INPUT_ID}
        rows={1}
        value={question}
        maxLength={MAX}
        aria-describedby={hintId}
        onChange={(event) => {
          setQuestion(event.target.value);
        }}
        onKeyDown={onKeyDown}
        placeholder={turns.length > 0 ? t("workspace.followUpPlaceholder") : t("workspace.placeholder")}
        className="block max-h-42 w-full resize-none bg-transparent px-2 py-2 text-[0.9375rem] leading-6 text-fg placeholder:text-fg-muted focus:outline-none"
      />
      <div className="flex items-center justify-between gap-2 px-1 pt-1">
        <div className="flex min-w-0 items-center gap-2">
          {turns.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={newConversation} disabled={busy}>
              <MessageSquarePlus />
              <span className="sr-only sm:not-sr-only">{t("workspace.newConversation")}</span>
            </Button>
          ) : null}
          <p id={hintId} className="hidden truncate text-micro text-fg-muted md:block">
            {t("workspace.hint")}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className={cn("figures text-micro", question.length > MAX * 0.9 ? "text-warning" : "text-fg-muted")}>
            {question.length > 0 ? `${question.length}/${MAX}` : ""}
          </span>
          {busy && runningRunId ? (
            <Button
              variant="danger"
              size="sm"
              onClick={() => {
                cancel(runningRunId).catch((error: unknown) => toast.error(errorMessage(error, t)));
              }}
            >
              <Square />
              {t("workspace.stop")}
            </Button>
          ) : (
            <Button type="submit" variant="primary" size="sm" disabled={!canSend}>
              <ArrowUp />
              <span className="sr-only sm:not-sr-only">{t("workspace.ask")}</span>
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}

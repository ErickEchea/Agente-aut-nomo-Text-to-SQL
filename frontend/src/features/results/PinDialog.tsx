import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pin } from "lucide-react";
import { useId, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import { useApi, useCan } from "../../app/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "../../components/ui/overlays";
import { Input } from "../../components/ui/primitives";
import { errorMessage } from "../../lib/errors";

const NEW = "__new__";

export function PinDialog({ runId, step, defaultTitle }: { runId: string; step: number; defaultTitle: string }) {
  const { t } = useTranslation();
  const api = useApi();
  const queryClient = useQueryClient();
  const { contribute } = useCan();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(defaultTitle);
  const [target, setTarget] = useState<string>("");
  const [newName, setNewName] = useState("");
  const ids = { title: useId(), board: useId(), name: useId() };

  const dashboards = useQuery({
    queryKey: ["dashboards"],
    queryFn: () => endpoints.listDashboards(api),
    enabled: open,
  });
  const editable = (dashboards.data ?? []).filter((d) => d.editable);
  const selected = target || editable[0]?.id || NEW;

  const pin = useMutation({
    mutationFn: async () => {
      let id = selected;
      let name = editable.find((d) => d.id === id)?.name ?? "";
      if (id === NEW) {
        const created = await endpoints.createDashboard(api, newName.trim());
        id = created.id;
        name = created.name;
      }
      await endpoints.pinToDashboard(api, id, { run_id: runId, step, title: title.trim() || defaultTitle });
      return name;
    },
    onSuccess: (name) => {
      void queryClient.invalidateQueries({ queryKey: ["dashboards"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      toast.success(t("pin.pinned", { name }));
      setOpen(false);
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });

  if (!contribute) return null;

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    pin.mutate();
  };
  const invalid = selected === NEW && newName.trim().length === 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm">
          <Pin />
          {t("pin.action")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("pin.title")} description={t("pin.description")}>
        <form onSubmit={submit} className="grid gap-4">
          <div className="grid gap-1.5">
            <label htmlFor={ids.title} className="text-small text-fg-secondary">
              {t("pin.titleLabel")}
            </label>
            <Input id={ids.title} value={title} maxLength={200} onChange={(e) => { setTitle(e.target.value); }} />
          </div>
          <div className="grid gap-1.5">
            <label htmlFor={ids.board} className="text-small text-fg-secondary">
              {t("pin.dashboard")}
            </label>
            <select
              id={ids.board}
              value={selected}
              onChange={(e) => {
                setTarget(e.target.value);
              }}
              className="h-10 rounded-md border border-line-strong bg-surface-2 px-3 text-fg focus-visible:border-accent"
            >
              {editable.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
              <option value={NEW}>{t("pin.newDashboard")}</option>
            </select>
          </div>
          {selected === NEW ? (
            <div className="grid gap-1.5">
              <label htmlFor={ids.name} className="text-small text-fg-secondary">
                {t("pin.newName")}
              </label>
              <Input id={ids.name} value={newName} maxLength={120} autoFocus onChange={(e) => { setNewName(e.target.value); }} />
            </div>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setOpen(false); }}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" variant="primary" disabled={pin.isPending || invalid}>
              <Pin />
              {pin.isPending ? t("common.saving") : t("pin.submit")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

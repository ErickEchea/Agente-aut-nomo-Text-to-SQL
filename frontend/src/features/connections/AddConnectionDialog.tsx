import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Plus, Plug, TriangleAlert } from "lucide-react";
import { useId, useState, type ReactNode, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import * as endpoints from "../../api/endpoints";
import type { ConnectionIn, ConnectionKind, ProbeOut } from "../../api/types";
import { useApi } from "../../app/auth";
import { Button } from "../../components/ui/button";
import { Dialog, DialogContent, DialogTrigger } from "../../components/ui/overlays";
import { Input, Spinner } from "../../components/ui/primitives";
import { errorMessage } from "../../lib/errors";

const DEFAULT_PORT: Record<ConnectionKind, string> = { postgresql: "5432", mysql: "3306", sqlite: "" };
const SELECT = "h-10 w-full rounded-md border border-line-strong bg-surface-2 px-3 text-fg focus-visible:border-accent";

interface Form {
  kind: ConnectionKind;
  name: string;
  host: string;
  port: string;
  database: string;
  username: string;
  password: string;
  schema: string;
  asOf: string;
  pii: string;
}

const EMPTY: Form = {
  kind: "postgresql",
  name: "",
  host: "",
  port: DEFAULT_PORT.postgresql,
  database: "",
  username: "",
  password: "",
  schema: "public",
  asOf: "",
  pii: "",
};

function toBody(form: Form, acknowledge: boolean): ConnectionIn {
  const network = form.kind !== "sqlite";
  return {
    name: form.name.trim(),
    kind: form.kind,
    database: form.database.trim(),
    host: network ? form.host.trim() : null,
    port: network && form.port ? Number(form.port) : null,
    username: network ? form.username.trim() : null,
    password: network && form.password ? form.password : null,
    schema_name: form.kind === "postgresql" ? form.schema.trim() || "public" : null,
    as_of: form.asOf || null,
    pii_columns: form.pii,
    acknowledge_writable: acknowledge,
    key: null,
  };
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-small text-fg-secondary">
        {label}
      </label>
      {children}
    </div>
  );
}

export function AddConnectionDialog() {
  const { t } = useTranslation();
  const api = useApi();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<Form>(EMPTY);
  const [probe, setProbe] = useState<ProbeOut | null>(null);
  const [acknowledge, setAcknowledge] = useState(false);
  const id = useId();
  const files = useQuery({ queryKey: ["sqlite-files"], queryFn: () => endpoints.sqliteFiles(api), enabled: open && form.kind === "sqlite" });

  const update = (patch: Partial<Form>) => {
    setForm((current) => ({ ...current, ...patch }));
    setProbe(null);
    setAcknowledge(false);
  };

  const test = useMutation({
    mutationFn: () => endpoints.testConnection(api, toBody(form, false)),
    onSuccess: setProbe,
    onError: (error) => toast.error(errorMessage(error, t)),
  });
  const save = useMutation({
    mutationFn: () => endpoints.createConnection(api, toBody(form, acknowledge)),
    onSuccess: (created) => {
      toast.success(t("connections.created", { name: created.name }));
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
      setOpen(false);
      setForm(EMPTY);
      setProbe(null);
    },
    onError: (error) => toast.error(errorMessage(error, t)),
  });

  const complete =
    form.name.trim().length >= 2 &&
    form.database.trim() !== "" &&
    (form.kind === "sqlite" || (form.host.trim() !== "" && form.username.trim() !== ""));
  const canSave = complete && probe?.ok === true && (!probe.writable || acknowledge);

  const submit = (event: SyntheticEvent) => {
    event.preventDefault();
    if (canSave) save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setProbe(null);
      }}
    >
      <DialogTrigger asChild>
        <Button variant="primary">
          <Plus />
          {t("connections.add")}
        </Button>
      </DialogTrigger>
      <DialogContent title={t("connections.addTitle")} description={t("connections.addDescription")} className="max-w-lg">
        <form onSubmit={submit} className="grid max-h-[70vh] gap-4 overflow-y-auto pr-1">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id={`${id}-kind`} label={t("connections.kind")}>
              <select
                id={`${id}-kind`}
                value={form.kind}
                className={SELECT}
                onChange={(e) => {
                  const kind = e.target.value as ConnectionKind;
                  update({ kind, port: DEFAULT_PORT[kind], database: "", schema: kind === "postgresql" ? "public" : "" });
                }}
              >
                {(["postgresql", "mysql", "sqlite"] as const).map((kind) => (
                  <option key={kind} value={kind}>
                    {t(`connections.kinds.${kind}`)}
                  </option>
                ))}
              </select>
            </Field>
            <Field id={`${id}-name`} label={t("connections.fields.name")}>
              <Input id={`${id}-name`} value={form.name} maxLength={120} onChange={(e) => { update({ name: e.target.value }); }} />
            </Field>
          </div>

          {form.kind === "sqlite" ? (
            <Field id={`${id}-file`} label={t("connections.fields.sqliteFile")}>
              {files.data && files.data.length > 0 ? (
                <select id={`${id}-file`} value={form.database} className={SELECT} onChange={(e) => { update({ database: e.target.value }); }}>
                  <option value="" disabled>
                    {t("connections.fields.sqliteFile")}
                  </option>
                  {files.data.map((file) => (
                    <option key={file} value={file}>
                      {file}
                    </option>
                  ))}
                </select>
              ) : (
                <p id={`${id}-file`} className="text-small text-fg-muted">
                  {files.isPending ? t("common.loading") : t("connections.noFiles")}
                </p>
              )}
            </Field>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-[1fr_7rem]">
                <Field id={`${id}-host`} label={t("connections.fields.host")}>
                  <Input id={`${id}-host`} value={form.host} autoComplete="off" onChange={(e) => { update({ host: e.target.value }); }} />
                </Field>
                <Field id={`${id}-port`} label={t("connections.fields.port")}>
                  <Input id={`${id}-port`} value={form.port} inputMode="numeric" onChange={(e) => { update({ port: e.target.value.replace(/\D/g, "") }); }} />
                </Field>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id={`${id}-db`} label={t("connections.fields.database")}>
                  <Input id={`${id}-db`} value={form.database} onChange={(e) => { update({ database: e.target.value }); }} />
                </Field>
                {form.kind === "postgresql" ? (
                  <Field id={`${id}-schema`} label={t("connections.fields.schema")}>
                    <Input id={`${id}-schema`} value={form.schema} onChange={(e) => { update({ schema: e.target.value }); }} />
                  </Field>
                ) : null}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field id={`${id}-user`} label={t("connections.fields.username")}>
                  <Input id={`${id}-user`} value={form.username} autoComplete="off" onChange={(e) => { update({ username: e.target.value }); }} />
                </Field>
                <Field id={`${id}-password`} label={t("connections.fields.password")}>
                  <Input id={`${id}-password`} type="password" autoComplete="new-password" value={form.password} onChange={(e) => { update({ password: e.target.value }); }} />
                </Field>
              </div>
            </>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Field id={`${id}-asof`} label={t("connections.fields.asOf")}>
              <Input id={`${id}-asof`} type="date" value={form.asOf} onChange={(e) => { update({ asOf: e.target.value }); }} />
            </Field>
            <Field id={`${id}-pii`} label={t("connections.fields.pii")}>
              <Input id={`${id}-pii`} value={form.pii} placeholder="clientes.email" onChange={(e) => { update({ pii: e.target.value }); }} />
            </Field>
          </div>

          {probe ? (
            probe.ok ? (
              <div role="status" className="grid gap-2 rounded-md border border-success/40 bg-success-soft px-3 py-2 text-small">
                <p className="flex items-center gap-2 text-success">
                  <CheckCircle2 aria-hidden="true" className="size-4" />
                  {t("connections.testOk", {
                    tables: probe.tables,
                    version: `${t(`connections.kinds.${form.kind}`)} ${probe.version ?? ""}`.trim(),
                  })}
                </p>
                {probe.writable ? (
                  <div className="grid gap-2 rounded-md border border-warning/50 bg-warning-soft px-3 py-2">
                    <p className="flex items-start gap-2 text-warning">
                      <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                      {t("connections.writable", { reasons: probe.writable_reasons.join("; ") })}
                    </p>
                    <label className="flex items-start gap-2 text-fg-secondary">
                      <input type="checkbox" checked={acknowledge} className="mt-1 accent-[var(--warning)]" onChange={(e) => { setAcknowledge(e.target.checked); }} />
                      {t("connections.acknowledge")}
                    </label>
                  </div>
                ) : null}
              </div>
            ) : (
              <p role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-small text-danger">
                {t("connections.testFail", { error: probe.error ?? "" })}
              </p>
            )
          ) : null}

          <div className="flex flex-wrap justify-end gap-2">
            <Button disabled={!complete || test.isPending} onClick={() => { test.mutate(); }}>
              {test.isPending ? <Spinner /> : <Plug />}
              {test.isPending ? t("connections.testing") : t("connections.test")}
            </Button>
            <Button type="submit" variant="primary" disabled={!canSave || save.isPending}>
              {save.isPending ? <Spinner /> : null}
              {t("connections.save")}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

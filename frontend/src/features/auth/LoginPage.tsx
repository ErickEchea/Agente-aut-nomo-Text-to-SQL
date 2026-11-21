import { Eye, LockKeyhole, ShieldCheck, Cpu } from "lucide-react";
import { motion, useReducedMotion } from "motion/react";
import { useId, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useLocation, useNavigate } from "react-router";

import { ApiError } from "../../api/client";
import { useAuth } from "../../app/auth";
import { usePreferences } from "../../app/preferences";
import { Logo } from "../../components/Logo";
import { Button } from "../../components/ui/button";
import { Input, Spinner } from "../../components/ui/primitives";
import { cn } from "../../lib/cn";
import { errorMessage } from "../../lib/errors";

function Hero() {
  const { t } = useTranslation();
  const reduced = useReducedMotion() ?? false;
  const points = [
    { icon: ShieldCheck, text: t("auth.heroPoints.safe") },
    { icon: Eye, text: t("auth.heroPoints.visible") },
    { icon: Cpu, text: t("auth.heroPoints.local") },
  ];
  const steps = ["understand", "retrieve_schema", "generate_sql", "validate", "execute", "explain"] as const;
  return (
    <div className="canvas-grid relative hidden flex-col justify-between overflow-hidden border-r border-line p-10 lg:flex">
      <Logo />
      <div className="grid max-w-lg gap-8">
        <h1 className="text-display text-fg">{t("auth.heroTitle")}</h1>
        <ul className="grid gap-3">
          {points.map(({ icon: Icon, text }) => (
            <li key={text} className="flex items-start gap-3 text-fg-secondary">
              <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent" />
              {text}
            </li>
          ))}
        </ul>
        <ol aria-hidden="true" className="grid gap-0 rounded-lg border border-line bg-surface-1/80 p-4">
          {steps.map((node, i) => (
            <motion.li
              key={node}
              initial={reduced ? false : { opacity: 0, x: -6 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: reduced ? 0 : 0.15 + i * 0.12, duration: reduced ? 0 : 0.3 }}
              className="relative flex items-center gap-3 py-1.5"
            >
              <span className={cn("size-2.5 rounded-full", i < steps.length - 1 ? "bg-success" : "bg-accent")} />
              <span className="text-small text-fg-secondary">{t(`timeline.nodes.${node}.name`)}</span>
              <span className="ml-auto label-micro">{t(`timeline.nodes.${node}.hint`)}</span>
            </motion.li>
          ))}
        </ol>
      </div>
      <p className="text-micro text-fg-muted">{t("app.tagline")}</p>
    </div>
  );
}

export function LoginPage() {
  const { t } = useTranslation();
  const { status, signIn, sessionExpired } = useAuth();
  const { locale, setLocale } = usePreferences();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const ids = { email: useId(), password: useId(), error: useId() };
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") return <Navigate to={from} replace />;

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
      void navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError(t("auth.invalid"));
      else if (err instanceof ApiError && err.status === 429) setError(t("auth.rateLimited", { seconds: err.retryAfterS ?? 60 }));
      else setError(errorMessage(err, t));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[1.1fr_1fr]">
      <Hero />
      <main className="flex flex-col px-6 py-8 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="lg:invisible">
            <Logo />
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setLocale(locale === "es" ? "en" : "es");
            }}
          >
            {locale === "es" ? t("language.en") : t("language.es")}
          </Button>
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center gap-8 py-10">
          <div className="grid gap-2">
            <span className="flex size-10 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-accent">
              <LockKeyhole aria-hidden="true" className="size-5" />
            </span>
            <h2 className="text-h1 text-fg">{t("auth.title")}</h2>
            <p className="text-fg-secondary">{t("auth.subtitle")}</p>
          </div>
          {sessionExpired && !error ? (
            <p role="status" className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-small text-warning">
              {t("auth.sessionExpired")}
            </p>
          ) : null}
          <form onSubmit={(event) => void submit(event)} className="grid gap-4" noValidate>
            <div className="grid gap-1.5">
              <label htmlFor={ids.email} className="text-small text-fg-secondary">
                {t("auth.email")}
              </label>
              <Input
                id={ids.email}
                type="email"
                autoComplete="username"
                required
                value={email}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? ids.error : undefined}
                onChange={(e) => {
                  setEmail(e.target.value);
                }}
              />
            </div>
            <div className="grid gap-1.5">
              <label htmlFor={ids.password} className="text-small text-fg-secondary">
                {t("auth.password")}
              </label>
              <Input
                id={ids.password}
                type="password"
                autoComplete="current-password"
                required
                value={password}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? ids.error : undefined}
                onChange={(e) => {
                  setPassword(e.target.value);
                }}
              />
            </div>
            {error ? (
              <p id={ids.error} role="alert" className="rounded-md border border-danger/40 bg-danger-soft px-3 py-2 text-small text-danger">
                {error}
              </p>
            ) : null}
            <Button type="submit" variant="primary" size="lg" disabled={pending || !email || !password} className="mt-2">
              {pending ? <Spinner /> : null}
              {pending ? t("auth.signingIn") : t("auth.submit")}
            </Button>
          </form>
          <p className="text-small text-fg-muted">{t("auth.demoHint")}</p>
        </div>
      </main>
    </div>
  );
}

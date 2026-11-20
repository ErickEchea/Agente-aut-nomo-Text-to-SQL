export const resources = {
  es: {
    translation: {
      app: { tagline: "Inteligencia de negocios autónoma" },
      status: {
        title: "Estado del sistema",
        subtitle: "Dependencias que el agente necesita para responder preguntas.",
        ready: "Operativo",
        notReady: "Degradado",
        loading: "Comprobando servicios…",
        unreachable: "No se puede contactar con la API. Verifica que el backend esté en ejecución.",
        retry: "Reintentar",
        latency: "{{ms}} ms",
        version: "Versión {{version}}",
        lastChecked: "Última comprobación: {{time}}",
        checks: {
          app_db: "Base de datos de la aplicación",
          demo_db: "Base de datos retail (solo lectura)",
          ollama: "Modelos locales (Ollama)",
        },
        ok: "OK",
        failed: "Falla",
      },
      language: { label: "Idioma", es: "Español", en: "English" },
    },
  },
  en: {
    translation: {
      app: { tagline: "Autonomous business intelligence" },
      status: {
        title: "System status",
        subtitle: "Dependencies the agent needs to answer questions.",
        ready: "Operational",
        notReady: "Degraded",
        loading: "Checking services…",
        unreachable: "Cannot reach the API. Make sure the backend is running.",
        retry: "Retry",
        latency: "{{ms}} ms",
        version: "Version {{version}}",
        lastChecked: "Last checked: {{time}}",
        checks: {
          app_db: "Application database",
          demo_db: "Retail database (read-only)",
          ollama: "Local models (Ollama)",
        },
        ok: "OK",
        failed: "Failing",
      },
      language: { label: "Language", es: "Español", en: "English" },
    },
  },
} as const;

export type Locale = keyof typeof resources;

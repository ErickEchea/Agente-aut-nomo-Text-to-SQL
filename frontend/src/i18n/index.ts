import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { initialLocale } from "../app/preferences";
import { resources } from "./resources";

void i18n.use(initReactI18next).init({
  resources,
  lng: typeof window === "undefined" ? "es" : initialLocale(),
  fallbackLng: "es",
  supportedLngs: ["es", "en"],
  interpolation: { escapeValue: false },
  returnObjects: false,
});

export default i18n;

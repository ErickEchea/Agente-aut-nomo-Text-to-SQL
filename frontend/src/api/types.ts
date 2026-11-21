/** Friendly aliases over the types generated from the backend OpenAPI contract (`make api-types`). */
import type { components } from "./schema";

type Schemas = components["schemas"];

export type User = Schemas["UserOut"];
export type Role = Schemas["Role"];
export type TokenResponse = Schemas["TokenResponse"];
export type RunCreated = Schemas["RunCreated"];
export type RunOut = Schemas["RunOut"];
export type RunSummary = Schemas["RunSummary"];
export type RunResult = Schemas["RunResult"];
export type RunStatus = RunResult["status"];
export type StepOut = Schemas["StepOut"];
export type AttemptOut = Schemas["AttemptOut"];
export type ChartSpec = Schemas["ChartSpec"];
export type ChartKind = ChartSpec["kind"];
export type EChartsOption = Schemas["EChartsOption"];
export type Kpi = Schemas["Kpi"];
export type ExplanationOut = Schemas["ExplanationOut"];
export type TimeRangeOut = Schemas["TimeRangeOut"];
export type FeedbackOut = Schemas["FeedbackOut"];
export type FrequentQuestion = Schemas["FrequentQuestion"];
export type Preferences = Schemas["Preferences"];
export type DashboardSummary = Schemas["DashboardSummary"];
export type DashboardOut = Schemas["DashboardOut"];
export type DashboardItemOut = Schemas["DashboardItemOut"];
export type ConnectionOut = Schemas["ConnectionOut"];
export type AuditEntry = Schemas["AuditEntry"];
export type ReadyResponse = Schemas["ReadyResponse"];
export type JsonScalar = string | number | boolean | null;

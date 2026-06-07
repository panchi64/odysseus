/** Health Dashboard feature data contracts. */

export type HealthStatus = "nominal" | "warn" | "alert" | "timeout" | "partial";

export interface ServiceStatus {
  id: string;
  name: string;
  status: HealthStatus;
  latencyMs: number;
  detail: string;
  history: HealthStatus[];
  degradationNote?: string;
}

export interface OverallHealth {
  status: HealthStatus;
  checkedAt: string;
  servicesUp: number;
  servicesTotal: number;
}

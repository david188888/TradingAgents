/**
 * Map the backend's stable error_category values (manager._error_category) to
 * short Chinese labels shown in the history sidebar and failed-run view.
 * The backend owns the vocabulary; an unknown category falls back to a
 * neutral label instead of rendering a raw internal identifier.
 */
export type ErrorCategory =
  | "provider_authentication"
  | "provider_timeout"
  | "vendor_rate_limit"
  | "evidence_rejection"
  | "checkpoint_incompatibility"
  | "missing_configuration"
  | "report_publication"
  | "unexpected_internal_failure";

const ERROR_LABELS: Record<ErrorCategory, string> = {
  provider_authentication: "凭证错误",
  provider_timeout: "供应商超时",
  vendor_rate_limit: "接口限流",
  evidence_rejection: "证据门驳回",
  checkpoint_incompatibility: "检查点不兼容",
  missing_configuration: "配置缺失",
  report_publication: "报告发布失败",
  unexpected_internal_failure: "内部错误",
};

export function errorCategoryLabel(category: string | null | undefined): string {
  if (!category) return "运行失败";
  return ERROR_LABELS[category as ErrorCategory] ?? "运行失败";
}

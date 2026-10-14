/** Credential-free SIWC Web contracts; tokens never cross this adapter. */
import type { ApiErrorResponse, ModelFailureDiagnosticDTO, ModelOptionDTO } from "./contracts";

export interface ChatGPTAccount {
  account_ref: string; label: string; signed_in: boolean; plan_enabled: boolean;
  usage_paused: boolean; revocation_unconfirmed: boolean;
}
export interface ChatGPTStatus { accounts: ChatGPTAccount[]; active_account_ref: string | null; usage_url: string }
export interface ChatGPTCatalog { account_ref: string; models: ModelOptionDTO[]; fetched_at: number }
export interface ChatGPTLogin { status: "pending" | "exchanging" | "complete" | "failed" | "expired" | "cancelled"; account_ref?: string | null; error?: string; first_sign_in?: boolean }

export class ChatGPTRequestError extends Error {
  constructor(message: string, readonly code = "request_failed", readonly status = 0,
    readonly diagnostic: ModelFailureDiagnosticDTO | null = null) { super(message); }
  get action(): ModelFailureDiagnosticDTO["action"] {
    if (this.diagnostic) return this.diagnostic.action;
    // Older local servers expose only the stable code/message envelope.
    if (["not_signed_in", "invalid_grant", "invalid_client", "invalid_identity", "session_changed", "authorization_rejected", "subscription_sharing_invalid_user"].includes(this.code) || this.status === 401) return "sign_in";
    if (this.code === "subscription_sharing_usage_limit_exceeded") return "manage_usage";
    if (["subscription_sharing_user_not_eligible", "chatpass_v2_scope_not_authorized", "chatpass_v2_invalid_authorization_context"].includes(this.code)) return "check_permissions";
    if (["subscription_sharing_unsupported_capability", "subscription_sharing_route_not_supported"].includes(this.code)) return "check_capability";
    if (this.status === 403) return "check_permissions";
    return "retry_later";
  }
  get transient(): boolean {
    const code = this.diagnostic?.upstream_code ?? this.code;
    if (this.action !== "retry_later") return false;
    if (["transport_timeout", "transport_connection_error"].includes(code)) return true;
    return ["request_failed", "transport_error"].includes(code) && (this.status === 0 || this.status === 408 || this.status >= 500);
  }
}

export async function chatgptRequest<T>(path: string, body?: object, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/chatgpt/${path}`, {
      signal,
      ...(body === undefined ? {} : {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      }),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ChatGPTRequestError("无法连接本地服务，请检查连接后重试。", "transport_error");
  }
  if (!response.ok) {
    const value = await response.json().catch(() => null) as ApiErrorResponse | null;
    throw new ChatGPTRequestError(value?.detail?.message ?? "ChatGPT 请求暂不可用，请重试。",
      value?.detail?.code, response.status, value?.detail?.diagnostic ?? null);
  }
  return response.json() as Promise<T>;
}

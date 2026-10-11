/** Credential-free SIWC Web contracts; tokens never cross this adapter. */
import type { ModelOptionDTO } from "./contracts";

export interface ChatGPTAccount {
  account_ref: string; label: string; signed_in: boolean; plan_enabled: boolean;
  usage_paused: boolean; revocation_unconfirmed: boolean;
}
export interface ChatGPTStatus { accounts: ChatGPTAccount[]; active_account_ref: string | null; usage_url: string }
export interface ChatGPTCatalog { account_ref: string; models: ModelOptionDTO[]; fetched_at: number }
export interface ChatGPTLogin { status: "pending" | "exchanging" | "complete" | "failed" | "expired" | "cancelled"; account_ref?: string | null; error?: string; first_sign_in?: boolean }

export async function chatgptRequest<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/chatgpt/${path}`, body === undefined ? undefined : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!response.ok) {
    const value = await response.json().catch(() => null) as {detail?: {message?: string}} | null;
    throw new Error(value?.detail?.message ?? "ChatGPT 请求暂不可用");
  }
  return response.json() as Promise<T>;
}

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatGPTRequestError, chatgptRequest, type ChatGPTStatus, type ChatGPTCatalog, type ChatGPTLogin } from "../api/chatgpt";

export function useChatGPT(enabled: boolean) {
  const [status, setStatus] = useState<ChatGPTStatus | null>(null);
  const [catalog, setCatalog] = useState<ChatGPTCatalog | null>(null);
  const [failure, setFailure] = useState<ChatGPTRequestError | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState<string | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [welcome, setWelcome] = useState(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;
  const controller = useRef<AbortController | null>(null);
  const pendingAttempt = useRef<string | null>(null);
  const ref = status?.active_account_ref ?? null;
  const account = status?.accounts.find(a => a.account_ref === ref) ?? null;
  const current = useCallback((id: number) => mounted.current && enabledRef.current && epoch.current === id, []);
  const report = useCallback((error: unknown) => setFailure(error instanceof ChatGPTRequestError
    ? error : new ChatGPTRequestError("ChatGPT 操作未完成，请重试。")), []);

  const invalidate = useCallback(() => {
    epoch.current++;
    controller.current?.abort();
    if (pendingAttempt.current) {
      void chatgptRequest(`login/${encodeURIComponent(pendingAttempt.current)}/cancel`, {}).catch(() => {});
      pendingAttempt.current = null;
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; invalidate(); };
  }, [invalidate]);

  const begin = useCallback(() => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    const id = ++epoch.current;
    setBusy(true); setFailure(null); setCatalog(null);
    return { id, signal: next.signal };
  }, []);

  // A single sequence owns both snapshots. Login/account changes explicitly run
  // it even when the account ref and stored permission flags stay unchanged.
  const load = useCallback(async (force: boolean, id: number, signal: AbortSignal) => {
    try {
      const next = await chatgptRequest<ChatGPTStatus>("status", undefined, signal);
      if (!current(id)) return;
      setStatus(next);
      const selected = next.accounts.find(a => a.account_ref === next.active_account_ref);
      if (!selected?.plan_enabled) return;
      let models: ChatGPTCatalog;
      try {
        models = await chatgptRequest<ChatGPTCatalog>(`models?account_ref=${encodeURIComponent(selected.account_ref)}&refresh=${force}`, undefined, signal);
      } catch (error) {
        // Read-only catalog recovery only. Never repeat quota/auth/capability
        // failures or send inference as a connection probe.
        if (!current(id) || !(error instanceof ChatGPTRequestError) || !error.transient) throw error;
        models = await chatgptRequest<ChatGPTCatalog>(`models?account_ref=${encodeURIComponent(selected.account_ref)}&refresh=true`, undefined, signal);
      }
      if (current(id)) {
        if (models.account_ref !== selected.account_ref || !models.models.length) {
          throw new ChatGPTRequestError("无法读取该账户模型列表，请重试。", "catalog_unavailable", 422);
        }
        setCatalog(models);
      }
    } catch (error) {
      if (!current(id)) return;
      report(error);
      // Refresh may have invalidated stored credentials. Keep the error while
      // reconciling that local status; never erase it with a secondary failure.
      try {
        const next = await chatgptRequest<ChatGPTStatus>("status", undefined, signal);
        if (current(id)) setStatus(next);
      } catch { /* The original failure remains actionable. */ }
    } finally {
      if (current(id)) setBusy(false);
    }
  }, [current, report]);

  const refresh = useCallback(async (force = true) => {
    if (!enabledRef.current) return;
    const { id, signal } = begin();
    await load(force, id, signal);
  }, [begin, load]);
  useEffect(() => {
    if (enabled) void refresh(false);
    else { setBusy(false); setCatalog(null); setFailure(null); setAttempt(null); setLoginUrl(null); }
    return invalidate;
  }, [enabled, refresh, invalidate]);

  const action = useCallback(async (path: string, body: object) => {
    const { id, signal } = begin();
    try {
      await chatgptRequest(path, body);
      if (current(id)) await load(true, id, signal);
    } catch (error) { if (current(id)) report(error); }
    finally { if (current(id)) setBusy(false); }
  }, [begin, current, load, report]);

  function login(existing = false) {
    // Open during the click to avoid popup blockers. No opener access is kept.
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    const { id } = begin();
    void chatgptRequest<{attempt_id: string; authorization_url: string}>("login", existing && ref ? {account_ref: ref} : {})
      .then(next => {
        if (!current(id)) {
          popup?.close();
          void chatgptRequest(`login/${encodeURIComponent(next.attempt_id)}/cancel`, {}).catch(() => {});
          return;
        }
        const url = new URL(next.authorization_url);
        if (url.origin !== "https://auth.openai.com" || url.pathname !== "/api/accounts/authorize") {
          void chatgptRequest(`login/${encodeURIComponent(next.attempt_id)}/cancel`, {}).catch(() => {});
          throw new ChatGPTRequestError("授权地址无效，请重试。", "invalid_identity", 422);
        }
        pendingAttempt.current = next.attempt_id;
        setAttempt(next.attempt_id); setLoginUrl(next.authorization_url);
        if (popup) popup.location.href = next.authorization_url;
      }).catch(error => { popup?.close(); if (current(id)) { report(error); setBusy(false); } });
  }
  useEffect(() => {
    if (!attempt) return;
    const id = epoch.current;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await chatgptRequest<ChatGPTLogin>(`login/${encodeURIComponent(attempt!)}`);
        if (!alive || !current(id)) return;
        if (next.status === "pending" || next.status === "exchanging") { timer = setTimeout(() => void poll(), 700); return; }
        pendingAttempt.current = null;
        setAttempt(null); setLoginUrl(null);
        if (next.status === "complete") {
          setWelcome(next.first_sign_in === true);
          await refresh(true);
        } else {
          setBusy(false);
          report(new ChatGPTRequestError(next.error ?? "登录已取消或过期，请重新尝试。", "login_incomplete", 422));
        }
      } catch (error) {
        if (alive && current(id)) {
          void chatgptRequest(`login/${encodeURIComponent(attempt!)}/cancel`, {}).catch(() => {});
          pendingAttempt.current = null;
          setBusy(false); setAttempt(null); setLoginUrl(null); report(error);
        }
      }
    }
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [attempt, current, refresh, report]);

  async function cancelLogin() {
    if (!attempt) return;
    const target = attempt;
    pendingAttempt.current = null;
    setAttempt(null); setLoginUrl(null);
    await action(`login/${encodeURIComponent(target)}/cancel`, {});
  }
  return { status, account, account_ref: ref, catalog: catalog?.account_ref === ref ? catalog : null,
    error: failure?.message ?? null, failure, busy,
    login, attempt, loginUrl, welcome, dismissWelcome: () => setWelcome(false), refresh,
    select: (account_ref: string) => action("account", {account_ref}),
    logout: () => ref ? action("logout", {account_ref: ref}) : Promise.resolve(),
    retryUsage: () => ref ? action("usage/retry", {account_ref: ref}) : Promise.resolve(), cancelLogin,
  };
}

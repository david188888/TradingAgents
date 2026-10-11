import { useCallback, useEffect, useRef, useState } from "react";
import { chatgptRequest, type ChatGPTStatus, type ChatGPTCatalog, type ChatGPTLogin } from "../api/chatgpt";

export function useChatGPT(enabled: boolean) {
  const [status, setStatus] = useState<ChatGPTStatus | null>(null);
  const [catalog, setCatalog] = useState<ChatGPTCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState<string | null>(null);
  const [loginUrl, setLoginUrl] = useState<string | null>(null);
  const [welcome, setWelcome] = useState(false);
  const epoch = useRef(0);
  const mounted = useRef(true);
  const pendingAttempt = useRef<string | null>(null);
  pendingAttempt.current = attempt;
  const ref = status?.active_account_ref ?? null;
  const account = status?.accounts.find(a => a.account_ref === ref) ?? null;

  useEffect(() => { mounted.current = true; return () => { mounted.current = false; epoch.current++; if (pendingAttempt.current) void chatgptRequest(`login/${pendingAttempt.current}/cancel`, {}).catch(() => {}); }; }, []);
  const loadStatus = useCallback(async () => {
    const next = await chatgptRequest<ChatGPTStatus>("status");
    if (mounted.current) setStatus(next);
  }, []);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    chatgptRequest<ChatGPTStatus>("status").then(next => { if (alive) setStatus(next); })
      .catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; epoch.current++; };
  }, [enabled]);

  const refresh = useCallback(async (force = true) => {
    const id = ++epoch.current;
    if (!ref || !account?.plan_enabled) { setCatalog(null); return; }
    setBusy(true); setError(null);
    try {
      const next = await chatgptRequest<ChatGPTCatalog>(`models?account_ref=${encodeURIComponent(ref)}&refresh=${force}`);
      if (mounted.current && epoch.current === id && next.account_ref === ref) setCatalog(next);
    } catch (e) {
      if (mounted.current && epoch.current === id) { setCatalog(null); setError(e instanceof Error ? e.message : "模型列表读取失败"); }
    } finally { if (mounted.current && epoch.current === id) setBusy(false); }
  }, [ref, account?.plan_enabled]);
  useEffect(() => { if (enabled) { setCatalog(null); void refresh(false); } }, [enabled, refresh]);

  const action = useCallback(async (path: string, body: object) => {
    setBusy(true); setError(null); epoch.current++;
    try { await chatgptRequest(path, body); await loadStatus(); }
    catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : "操作失败"); }
    finally { if (mounted.current) setBusy(false); }
  }, [loadStatus]);
  function login(existing = false) {
    // Open during the click to avoid popup blockers. No opener access is kept.
    const popup = window.open("about:blank", "_blank");
    if (popup) popup.opener = null;
    setBusy(true); setError(null);
    void chatgptRequest<{attempt_id: string; authorization_url: string}>("login", existing && ref ? {account_ref: ref} : {})
      .then(next => {
        if (!mounted.current) { popup?.close(); void chatgptRequest(`login/${next.attempt_id}/cancel`, {}); return; }
        const url = new URL(next.authorization_url);
        if (url.origin !== "https://auth.openai.com" || url.pathname !== "/api/accounts/authorize") throw new Error("授权地址无效");
        setAttempt(next.attempt_id); setLoginUrl(next.authorization_url);
        if (popup) popup.location.href = next.authorization_url;
      }).catch(e => { popup?.close(); if (mounted.current) { setError(e.message); setBusy(false); } });
  }
  useEffect(() => {
    if (!attempt) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await chatgptRequest<ChatGPTLogin>(`login/${encodeURIComponent(attempt!)}`);
        if (!alive) return;
        if (next.status === "pending" || next.status === "exchanging") { timer = setTimeout(() => void poll(), 700); return; }
        setAttempt(null); setLoginUrl(null); setBusy(false);
        if (next.status === "complete") { setWelcome(next.first_sign_in === true); await loadStatus(); }
        else setError(next.error ?? "登录已取消或过期，请重新尝试。");
      } catch (e) { if (alive) { setBusy(false); setError(e instanceof Error ? e.message : "登录状态读取失败"); setAttempt(null); } }
    }
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [attempt, loadStatus]);

  return { status, account, account_ref: ref, catalog: catalog?.account_ref === ref ? catalog : null, error, busy,
    login, attempt, loginUrl, welcome, dismissWelcome: () => setWelcome(false), refresh,
    select: (account_ref: string) => action("account", {account_ref}),
    logout: () => ref ? action("logout", {account_ref: ref}) : Promise.resolve(),
    retryUsage: () => ref ? action("usage/retry", {account_ref: ref}) : Promise.resolve(),
    cancelLogin: () => attempt ? action(`login/${attempt}/cancel`, {}).then(() => {setAttempt(null);setLoginUrl(null);}) : Promise.resolve(),
  };
}

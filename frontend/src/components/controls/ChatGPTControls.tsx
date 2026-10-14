import { useEffect, useId, useRef } from "react";
import type { useChatGPT } from "../../hooks/useChatGPT";

export function ChatGPTControls({ auth }: {auth: ReturnType<typeof useChatGPT>}) {
  const id = useId();
  const needsLogin = !auth.account?.plan_enabled || auth.failure?.action === "sign_in";
  const permissionFailure = auth.failure?.action === "check_permissions";
  const usagePaused = auth.account?.usage_paused || auth.failure?.action === "manage_usage";
  const status = auth.attempt ? "等待完成认证" : auth.busy ? "正在检查连接…"
    : auth.error ? needsLogin ? "需要重新认证" : usagePaused ? "用量受限" : "模型暂不可用"
    : needsLogin ? "等待授权" : usagePaused ? "用量已暂停" : auth.catalog ? "模型已就绪" : "等待读取模型";
  return <div className="input-group chatgpt-controls" aria-label="ChatGPT 订阅配置">
    <div className="chatgpt-connection" role="status"><span className={`connection-dot${auth.catalog && !auth.error && !usagePaused ? " ready" : ""}`} /><strong>{status}</strong></div>
    <small>使用 ChatGPT 订阅额度，模型随账户更新。</small>
    {!!auth.status?.accounts.length && <>
      <label htmlFor={id}>ChatGPT 账户</label>
      <select id={id} value={auth.account_ref ?? ""} onChange={e => void auth.select(e.target.value)} disabled={auth.busy}>
        {auth.status.accounts.map(a => <option key={a.account_ref} value={a.account_ref}>{a.label}{a.plan_enabled ? "" : " · 需授权"}</option>)}
      </select>
    </>}
    {auth.error && <p className="connection-error" role="alert">{auth.error}</p>}
    <div className="connection-actions">
      {needsLogin && !auth.attempt && <button className="secondary" type="button" disabled={auth.busy} onClick={() => auth.login(!!auth.account)}>{auth.account ? "重新认证" : "Continue with ChatGPT"}</button>}
      {!needsLogin && !auth.attempt && !usagePaused && <button className="secondary" type="button" disabled={auth.busy} onClick={() => void auth.refresh()}>{auth.error ? "重试加载模型" : "刷新模型"}</button>}
      {permissionFailure && !needsLogin && <button className="secondary" type="button" disabled={auth.busy} onClick={() => auth.login(true)}>重新认证</button>}
      {usagePaused && <>
        <a className="connection-link" href={auth.status?.usage_url ?? "https://chatgpt.com/settings/usage"} target="_blank" rel="noopener noreferrer">管理用量 ↗</a>
        <button className="secondary" type="button" disabled={auth.busy} onClick={() => void auth.retryUsage()}>重新尝试</button>
      </>}
      {auth.error && !auth.status && <button className="secondary" type="button" disabled={auth.busy} onClick={() => void auth.refresh()}>重试连接</button>}
    </div>
    {auth.attempt && <div className="connection-login">
      <p>请在 OpenAI 官方页面完成登录与授权，完成后模型会自动加载。</p>
      <div className="connection-actions">
        {auth.loginUrl && <a className="connection-link" href={auth.loginUrl} target="_blank" rel="noopener noreferrer">打开官方登录页面 ↗</a>}
        <button className="secondary" type="button" onClick={() => void auth.cancelLogin()}>取消登录</button>
      </div>
    </div>}
    {auth.account && <details className="account-options">
      <summary>账户选项</summary>
      <div className="connection-actions">
        {!needsLogin && !permissionFailure && <button className="secondary" type="button" disabled={auth.busy} onClick={() => auth.login(true)}>重新认证</button>}
        <button className="secondary" type="button" disabled={auth.busy} onClick={() => auth.login()}>添加账户</button>
        <a className="connection-link" href={auth.status?.usage_url ?? "https://chatgpt.com/settings/usage"} target="_blank" rel="noopener noreferrer">管理用量 ↗</a>
        {auth.account.signed_in && <button className="secondary account-logout" type="button" disabled={auth.busy} onClick={() => void auth.logout()}>退出此账户</button>}
      </div>
    </details>}
    {auth.catalog && !usagePaused && <small>模型更新于 {new Date(auth.catalog.fetched_at * 1000).toLocaleTimeString("zh-CN", {hour: "2-digit", minute: "2-digit"})}</small>}
    {auth.account?.revocation_unconfirmed && <p role="status" className="connection-note">已在本地退出，远端撤销未确认。可在 ChatGPT 设置中断开应用。</p>}
    {auth.welcome && <PlanWelcome onClose={auth.dismissWelcome} />}
  </div>;
}

function PlanWelcome({onClose}: {onClose: () => void}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal?.(); }, []);
  return <dialog ref={dialog} aria-label="ChatGPT 订阅已连接" onCancel={event => {event.preventDefault();onClose();}}>
    <p>已连接 ChatGPT。合格的模型请求会使用你的计划额度。</p>
    <p><a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">管理用量</a></p>
    <button type="button" onClick={onClose}>知道了</button>
  </dialog>;
}

import { useEffect, useId, useRef } from "react";
import type { useChatGPT } from "../../hooks/useChatGPT";

export function ChatGPTControls({ auth }: {auth: ReturnType<typeof useChatGPT>}) {
  const id = useId();
  return <div className="input-group chatgpt-controls" aria-label="ChatGPT 订阅配置">
    <strong>使用 ChatGPT 订阅</strong>
    <small>此处请求使用你的 ChatGPT 计划额度。模型按官方账户目录展示。</small>
    {!!auth.status?.accounts.length && <>
      <label htmlFor={id}>ChatGPT 账户</label>
      <select id={id} value={auth.account_ref ?? ""} onChange={e => void auth.select(e.target.value)} disabled={auth.busy}>
        {auth.status.accounts.map(a => <option key={a.account_ref} value={a.account_ref}>{a.label}{a.plan_enabled ? "" : " · 需授权"}</option>)}
      </select>
    </>}
    {!auth.account?.plan_enabled && <button type="button" disabled={auth.busy} onClick={() => auth.login(!!auth.account)}>Continue with ChatGPT</button>}
    {auth.account?.plan_enabled && <>
      <span>已授权 · 使用 ChatGPT 订阅</span>
      <button type="button" disabled={auth.busy} onClick={() => void auth.refresh()}>刷新模型</button>
    </>}
    {auth.account && <>
      <button type="button" disabled={auth.busy} onClick={() => auth.login()}>添加账户</button>
      {auth.account.signed_in && <button type="button" disabled={auth.busy} onClick={() => void auth.logout()}>退出此账户</button>}
    </>}
    {auth.attempt && <><span role="status">请在 OpenAI 官方页面完成登录与授权。</span>
      <button type="button" onClick={() => void auth.cancelLogin()}>取消登录</button></>}
    {auth.loginUrl && <a href={auth.loginUrl} target="_blank" rel="noopener noreferrer">打开官方登录页面</a>}
    {auth.welcome && <PlanWelcome onClose={auth.dismissWelcome} />}
    {auth.account?.usage_paused && <div role="status">计划或此应用用量已达到限制。管理用量后可主动重新尝试。
      <button type="button" disabled={auth.busy} onClick={() => void auth.retryUsage()}>重新尝试</button></div>}
    {auth.account?.revocation_unconfirmed && <p role="status">已在本地退出，远端撤销未确认。可在 ChatGPT 设置中断开应用。</p>}
    <a href={auth.status?.usage_url ?? "https://chatgpt.com/settings/usage"} target="_blank" rel="noopener noreferrer">管理用量</a>
    {auth.catalog && <small>模型更新于 {new Date(auth.catalog.fetched_at * 1000).toLocaleString("zh-CN")}</small>}
    {auth.busy && !auth.attempt && <span role="status">正在读取账户或模型…</span>}
    {auth.error && <p role="alert">{auth.error}</p>}
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

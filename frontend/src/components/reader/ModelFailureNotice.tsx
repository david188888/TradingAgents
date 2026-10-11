import type { ModelFailureDiagnosticDTO } from "../../api/contracts";

export function ModelFailureNotice({ failures }: {failures: ModelFailureDiagnosticDTO[]}) {
  if (!failures.length) return null;
  return <aside aria-label="模型调用提示" role="status">
    {failures.map(failure => <p key={failure.stage}>
      {failure.safe_message}
      {failure.action === "manage_usage" ? <a href="https://chatgpt.com/settings/usage" target="_blank" rel="noopener noreferrer">管理用量</a> : null}
      {failure.action === "sign_in" || failure.action === "refresh_models" ? " 请在模型配置中重新登录或刷新模型。" : null}
      {failure.request_id ? <small> 请求编号：{failure.request_id}</small> : null}
    </p>)}
  </aside>;
}

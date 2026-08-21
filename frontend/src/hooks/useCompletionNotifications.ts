import type { BatchSnapshotDTO, RunSnapshotDTO } from "../api/contracts";

const PREFERENCE_KEY = "tradingagents.completion-notifications";
const DELIVERED_KEY = "tradingagents.completion-notifications.delivered";

function notificationSupported(): boolean {
  return typeof window !== "undefined" && "Notification" in window;
}

export function notificationsEnabled(): boolean {
  if (typeof window === "undefined") return true;
  return window.localStorage.getItem(PREFERENCE_KEY) !== "off";
}

export async function requestCompletionNotificationPermission(): Promise<NotificationPermission | "unsupported"> {
  if (!notificationSupported() || !notificationsEnabled()) return "unsupported";
  if (Notification.permission === "granted" || Notification.permission === "denied") return Notification.permission;
  return Notification.requestPermission();
}

function markDelivered(identity: string): boolean {
  if (typeof window === "undefined") return false;
  const delivered = new Set(JSON.parse(window.localStorage.getItem(DELIVERED_KEY) ?? "[]") as string[]);
  if (delivered.has(identity)) return false;
  delivered.add(identity);
  window.localStorage.setItem(DELIVERED_KEY, JSON.stringify([...delivered].slice(-100)));
  return true;
}

function send(identity: string, title: string, body: string, onClick?: () => void): void {
  if (!notificationSupported() || !notificationsEnabled() || Notification.permission !== "granted") return;
  if (!markDelivered(identity)) return;
  const notification = new Notification(title, { body, tag: identity });
  notification.onclick = () => {
    window.focus();
    onClick?.();
    notification.close();
  };
}

export function notifyRun(snapshot: Pick<RunSnapshotDTO, "run_id" | "status" | "ticker"> & { error_message?: string | null }, onClick?: () => void): void {
  if (snapshot.status === "completed") {
    send(`run:${snapshot.run_id}:completed`, `${snapshot.ticker} 分析完成`, "研究报告已生成，点击查看 Reader。", onClick);
  } else if (snapshot.status === "failed") {
    send(`run:${snapshot.run_id}:failed`, `${snapshot.ticker} 分析失败`, snapshot.error_message ?? "分析任务失败，点击查看运行记录。", onClick);
  }
}

export function notifyBatch(snapshot: BatchSnapshotDTO, onClick?: () => void): void {
  if (!["completed", "partial", "failed", "cancelled"].includes(snapshot.status)) return;
  const body = `${snapshot.completed_count} 完成 · ${snapshot.failed_count} 失败 · ${snapshot.cancelled_count} 取消`;
  send(`batch:${snapshot.batch_id}:${snapshot.status}`, "批量分析已结束", body, onClick);
}

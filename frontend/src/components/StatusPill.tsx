const LABELS: Record<string, string> = {
  completed: "完成",
  processing: "處理中",
  pending: "等待中",
  failed: "失敗",
};

export default function StatusPill({ status }: { status: string }) {
  return <span className={`status-pill status-${status}`}>{LABELS[status] ?? status}</span>;
}

import { useRef, useState } from "react";

const ARM_TIMEOUT_MS = 3000;

// First click arms the button (shows confirmLabel for ARM_TIMEOUT_MS); only
// a second click while armed actually fires onConfirm. Replaces
// window.confirm() — a native dialog is easy to dismiss reflexively
// (Enter/Space muscle memory), whereas this requires a deliberate second
// click on the same spot, which is harder to trigger by accident in a dense
// list of cards.
export default function ConfirmDeleteButton({
  onConfirm,
  label = "🗑",
  confirmLabel = "確定？",
  title = "刪除",
  style,
}: {
  onConfirm: () => void | Promise<void>;
  label?: string;
  confirmLabel?: string;
  title?: string;
  style?: React.CSSProperties;
}) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<number | null>(null);

  function disarm() {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setArmed(false);
  }

  async function handleClick() {
    if (!armed) {
      setArmed(true);
      timerRef.current = window.setTimeout(disarm, ARM_TIMEOUT_MS);
      return;
    }
    disarm();
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={busy}
      title={armed ? "再按一次確認刪除" : title}
      style={{ fontSize: 12, color: armed ? "#e5484d" : undefined, ...style }}
    >
      {busy ? "…" : armed ? confirmLabel : label}
    </button>
  );
}

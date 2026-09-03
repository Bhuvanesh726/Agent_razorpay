interface Props {
  onClose: () => void;
  children: React.ReactNode;
  maxWidth?: string;
}

/** Shared overlay chrome for dialogs — the one place a real box-shadow is
 * used (an elevated surface floating over content genuinely needs one),
 * consistent backdrop, click-outside-to-close, radius, and padding. */
export default function Modal({ onClose, children, maxWidth = "max-w-lg" }: Props) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`max-h-[85vh] w-full ${maxWidth} overflow-y-auto rounded-lg bg-surface p-6 shadow-elevated`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

"use client";

import { useEffect, useState } from "react";
import type { HelpContent } from "@/lib/help";

// A small "what am I looking at?" affordance: an ⓘ button that opens a modal explaining every
// value on the page and how to read it. Content is data (lib/help.ts), so pages stay declarative.
export function InfoButton({
  content,
  className = "",
}: {
  content: HelpContent;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`How to read this page: ${content.title}`}
        title="What am I looking at?"
        className={`inline-grid h-5 w-5 place-items-center rounded-full border border-border text-faint transition hover:border-accent hover:text-accent ${className}`}
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 11v5" />
          <path d="M12 8h.01" />
        </svg>
      </button>

      {open && <Modal content={content} onClose={() => setOpen(false)} />}
    </>
  );
}

function Modal({ content, onClose }: { content: HelpContent; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-8"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={content.title}
    >
      <div
        className="panel my-auto w-full max-w-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border-soft px-5 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight">{content.title}</h2>
            {content.intro && (
              <p className="mt-1 text-[13px] leading-relaxed text-muted">{content.intro}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-md border border-border px-2 py-1 text-xs text-muted transition hover:border-accent hover:text-accent"
          >
            Esc
          </button>
        </div>

        <div className="max-h-[70vh] space-y-5 overflow-y-auto px-5 py-4">
          {content.sections.map((section, si) => (
            <section key={si}>
              {section.title && <div className="label mb-2">{section.title}</div>}
              <dl className="space-y-2.5">
                {section.rows.map((row, ri) => (
                  <div key={ri} className="grid gap-1 sm:grid-cols-[minmax(120px,190px)_1fr] sm:gap-3">
                    <dt className="text-[13px] font-medium text-text">{row.term}</dt>
                    <dd className="text-[13px] leading-snug text-muted">{row.desc}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}

          {content.analyse && content.analyse.length > 0 && (
            <section className="rounded-lg border border-border-soft bg-surface/60 p-4">
              <div className="label mb-2" style={{ color: "#2DD4BF" }}>
                How to read it
              </div>
              <ul className="list-disc space-y-1.5 pl-4 text-[13px] leading-snug text-muted marker:text-accent">
                {content.analyse.map((line, i) => (
                  <li key={i}>{line}</li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { useState } from "react";
import { Markdown } from "@/components/Markdown";

// Long readmes collapse to roughly a screen; cut lands on a line break, never mid-sentence.
const COLLAPSED_CHARS = 1800;

function clipAtLine(text: string, limit: number): string {
  const head = text.slice(0, limit);
  const nl = head.lastIndexOf("\n");
  return nl > limit * 0.5 ? head.slice(0, nl) : head;
}

function chipLabel(tag: string): string {
  return tag.startsWith("license:") ? `${tag.slice("license:".length)} license` : tag;
}

export function CollectedPanel({
  description,
  tags,
}: {
  description: string | null;
  tags: string[];
}) {
  const [open, setOpen] = useState(false);
  if (!description && tags.length === 0) return null;
  const long = (description ?? "").length > COLLAPSED_CHARS;
  const shown =
    description == null ? null : open || !long ? description : clipAtLine(description, COLLAPSED_CHARS);
  return (
    <div className="panel p-4">
      <div className="label mb-2">What we collected</div>
      {tags.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {tags.map((t) => (
            <span
              key={t}
              className="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted"
            >
              {chipLabel(t)}
            </span>
          ))}
        </div>
      )}
      {shown && <Markdown text={shown} />}
      {long && (
        <button
          onClick={() => setOpen(!open)}
          className="mt-1 text-xs text-accent hover:underline"
        >
          {open ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}

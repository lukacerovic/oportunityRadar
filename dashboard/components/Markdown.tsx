// Markdown-lite: headings, bullets, **bold**, `code`, [links](url) and ``` fences — rendered
// without a markdown dependency. Shared by the ✨ narration panel and "What we collected"
// (readmes), so it also strips raw HTML: <img> vanishes (no images by design), <a> keeps its
// text as a link, every other tag is dropped.
import React from "react";

function sanitize(text: string): string {
  return text
    .replace(/<a\s+[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/gi, "[$2]($1)")
    .replace(/<img[^>]*>/gi, "")
    .replace(/<\/?[a-zA-Z][^>]*>/g, "");
}

function inline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\))/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-text">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="rounded bg-card-hover px-1 text-[11px] text-accent">
          {part.slice(1, -1)}
        </code>
      );
    }
    const link = part.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
    if (link) {
      return (
        <a
          key={i}
          href={link[2]}
          target="_blank"
          rel="noreferrer"
          className="text-accent hover:underline"
        >
          {link[1]}
        </a>
      );
    }
    return part;
  });
}

export function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  let fence: string[] | null = null;
  const flush = (key: number) => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul-${key}`} className="mb-2 list-disc space-y-1 pl-4">
        {bullets.map((b, i) => (
          <li key={i}>{inline(b)}</li>
        ))}
      </ul>
    );
    bullets = [];
  };
  sanitize(text)
    .split("\n")
    .forEach((raw, i) => {
      const line = raw.trim();
      if (fence !== null) {
        if (line.startsWith("```")) {
          blocks.push(
            <pre
              key={`pre-${i}`}
              className="mb-2 overflow-x-auto rounded bg-card-hover p-2 text-[11px] leading-relaxed text-muted"
            >
              {fence.join("\n")}
            </pre>
          );
          fence = null;
        } else {
          fence.push(raw);
        }
        return;
      }
      if (line.startsWith("```")) {
        flush(i);
        fence = [];
        return;
      }
      if (line.startsWith("- ") || line.startsWith("* ")) {
        bullets.push(line.slice(2));
        return;
      }
      flush(i);
      if (!line) return;
      const heading = line.match(/^#{1,4}\s+(.*)$/);
      if (heading) {
        blocks.push(
          <h4
            key={i}
            className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-text first:mt-0"
          >
            {inline(heading[1])}
          </h4>
        );
      } else {
        blocks.push(
          <p key={i} className="mb-2">
            {inline(line)}
          </p>
        );
      }
    });
  flush(-1);
  return <div className="text-xs leading-relaxed text-muted">{blocks}</div>;
}

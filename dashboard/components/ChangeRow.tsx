import Link from "next/link";
import type { ChangeItem } from "@/lib/types";

export function ChangeRow({ item }: { item: ChangeItem }) {
  const body = (
    <div className="panel px-4 py-2.5 text-sm transition hover:bg-card-hover">{item.text}</div>
  );
  return item.entity_id ? <Link href={`/entity/${item.entity_id}`}>{body}</Link> : body;
}

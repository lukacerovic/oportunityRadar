"use client";

import type { ChangeItem } from "@/lib/types";
import { GroupedList } from "@/components/GroupedList";
import { ChangeRow } from "@/components/ChangeRow";

// Thin client wrapper: GroupedList needs closures (getCategory/renderItem), and functions
// can't cross the server→client boundary from an async page component — so this component
// owns them and only takes plain, serializable props.
export function ChangesGroupedList({
  items,
  itemLabel,
}: {
  items: ChangeItem[];
  itemLabel: string;
}) {
  return (
    <GroupedList
      items={items}
      keyOf={(it) => `${it.entity_id ?? "x"}-${it.text}`}
      getCategory={(it) => it.category}
      getSearchText={(it) => it.text}
      renderItem={(it) => <ChangeRow item={it} />}
      itemLabel={itemLabel}
    />
  );
}

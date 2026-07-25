"use client";

import type { GateDecisionItem } from "@/lib/types";
import { GroupedList } from "@/components/GroupedList";
import { GateRow } from "@/components/GateRow";

export function GateSuppressedList({ items }: { items: GateDecisionItem[] }) {
  return (
    <GroupedList
      items={items}
      keyOf={(d) => d.entity_id}
      getCategory={(d) => d.category}
      getSearchText={(d) => d.name}
      renderItem={(d) => <GateRow d={d} tone="suppressed" />}
      itemLabel="suppressed candidates"
    />
  );
}

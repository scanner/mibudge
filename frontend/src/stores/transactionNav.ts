//
// Transaction navigation store — holds the ordered list of transaction
// IDs from the most recent list view so the detail view can offer
// prev/next navigation without re-fetching.
//

// 3rd party imports
//
import { defineStore } from "pinia";
import { ref } from "vue";

////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////
//
export const useTransactionNavStore = defineStore("transactionNav", () => {
  const orderedIds = ref<string[]>([]);
  const savedSearch = ref("");
  const savedFilter = ref("");

  function setIds(ids: string[]) {
    orderedIds.value = ids;
  }

  function prevId(currentId: string): string | null {
    const idx = orderedIds.value.indexOf(currentId);
    return idx > 0 ? orderedIds.value[idx - 1] : null;
  }

  function nextId(currentId: string): string | null {
    const idx = orderedIds.value.indexOf(currentId);
    return idx >= 0 && idx < orderedIds.value.length - 1 ? orderedIds.value[idx + 1] : null;
  }

  return { orderedIds, savedSearch, savedFilter, setIds, prevId, nextId };
});

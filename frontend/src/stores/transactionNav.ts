//
// Transaction navigation store: the ordered ids of the rows the
// transaction list last showed (after its filter and search), so the
// detail view can step to the previous / next row without refetching.
// Also remembers the list's search and filter across a visit to the
// detail view.  Store layer.
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

  function reset() {
    orderedIds.value = [];
    savedSearch.value = "";
    savedFilter.value = "";
  }

  return { orderedIds, savedSearch, savedFilter, setIds, prevId, nextId, reset };
});

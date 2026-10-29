<template>
  <div>
    <h2 class="page-title">Equipment Catalogue</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="warning" class="warning">{{ warning }}</p>
    <p v-if="success" class="success">{{ success }}</p>

    <form class="card add-form" @submit.prevent="addItem">
      <label class="field">
        <span>Equipment name</span>
        <input
          ref="nameInput"
          v-model.trim="newName"
          list="equipment-suggestions"
          placeholder="e.g. Projector"
          required
        />
        <datalist id="equipment-suggestions">
          <option v-for="s in availableSuggestions" :key="s" :value="s" />
        </datalist>
      </label>
      <label class="field qty">
        <span>Total quantity</span>
        <input v-model.number="newQuantity" type="number" min="0" required />
      </label>
      <button class="btn btn-primary" type="submit">Add item</button>

      <div v-if="availableSuggestions.length" class="chips">
        <span class="hint">Quick add:</span>
        <button
          v-for="s in availableSuggestions"
          :key="s"
          type="button"
          class="chip"
          @click="pick(s)"
        >
          {{ s }}
        </button>
      </div>
    </form>

    <div v-if="items.length" class="toolbar">
      <div class="tabs" role="tablist">
        <button
          v-for="t in tabs"
          :key="t.value"
          type="button"
          role="tab"
          :aria-selected="filter === t.value"
          :class="['tab', { active: filter === t.value }]"
          @click="filter = t.value"
        >
          {{ t.label }} <span class="tab-count">{{ t.count }}</span>
        </button>
      </div>
      <input
        v-model="search"
        class="search"
        type="search"
        placeholder="Search equipment…"
        aria-label="Search equipment"
      />
    </div>

    <div v-if="filtered.length" class="card">
      <div class="table-wrap">
        <table class="items">
          <thead>
            <tr>
              <th>Equipment</th>
              <th>Total</th>
              <th>Status</th>
              <th class="right">Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in filtered" :key="item.id" :class="{ off: item.status !== 'active' }">
              <td class="item-name">{{ item.name }}</td>
              <td>
                <span v-if="editingId !== item.id">
                  {{ item.totalQuantity }}
                  <button type="button" class="link" @click="startEdit(item)">Edit</button>
                </span>
                <span v-else class="edit">
                  <input
                    v-model.number="editQuantity"
                    type="number"
                    min="0"
                    aria-label="New total quantity"
                    @keyup.enter="saveQuantity(item)"
                    @keyup.esc="editingId = null"
                  />
                  <button type="button" class="btn btn-sky" @click="saveQuantity(item)">Save</button>
                  <button type="button" class="link" @click="editingId = null">Cancel</button>
                </span>
              </td>
              <td><StatusBadge kind="item" :status="item.status" /></td>
              <td class="right">
                <template v-if="item.status === 'active'">
                  <span v-if="reportingId === item.id" class="item-actions">
                    <span class="hint">What's wrong?</span>
                    <button
                      v-for="r in REASONS"
                      :key="r.value"
                      type="button"
                      class="btn btn-rose"
                      @click="markUnavailable(item, r.value)"
                    >
                      {{ r.label }}
                    </button>
                    <button type="button" class="link" @click="reportingId = null">Cancel</button>
                  </span>
                  <button v-else type="button" class="link muted-link" @click="reportingId = item.id">
                    Report issue
                  </button>
                </template>
                <button v-else type="button" class="btn btn-sky" @click="markActive(item)">
                  Restore to service
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div v-else-if="items.length" class="card empty"><p>{{ emptyMessage }}</p></div>
    <div v-else class="card empty"><p>No equipment yet. Add your first item above.</p></div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from "vue";
import equipmentApi from "../api/equipment";
import StatusBadge from "../components/StatusBadge.vue";
import { useConfirm } from "../composables/useConfirm";

const SUGGESTIONS = [
  "Projector", "Microphone", "Speaker", "Extension cord", "Laptop",
  "HDMI cable", "Podium", "Whiteboard", "Camera", "Stage lighting",
];
const REASONS = [
  { value: "damaged", label: "Damaged" },
  { value: "maintenance", label: "Under maintenance" },
];

const items = ref([]);
const error = ref("");
const warning = ref("");
const success = ref("");
const newName = ref("");
const newQuantity = ref(1);
const search = ref("");
const filter = ref("all");
const editingId = ref(null);
const editQuantity = ref(0);
const reportingId = ref(null);
const nameInput = ref(null);
const { confirm } = useConfirm();

function message(e, fallback) {
  return e.response?.data?.error || fallback;
}

function clearMessages() {
  error.value = "";
  warning.value = "";
  success.value = "";
}

const availableSuggestions = computed(() => {
  const have = new Set(items.value.map((i) => i.name.toLowerCase()));
  return SUGGESTIONS.filter((s) => !have.has(s.toLowerCase()));
});

const activeCount = computed(() => items.value.filter((i) => i.status === "active").length);

const tabs = computed(() => [
  { value: "all", label: "All", count: items.value.length },
  { value: "active", label: "Active", count: activeCount.value },
  { value: "unavailable", label: "Unavailable", count: items.value.length - activeCount.value },
]);

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase();
  return items.value.filter((i) => {
    if (filter.value === "active" && i.status !== "active") return false;
    if (filter.value === "unavailable" && i.status === "active") return false;
    return !q || i.name.toLowerCase().includes(q);
  });
});

const emptyMessage = computed(() => {
  if (search.value.trim()) return `No equipment matches “${search.value.trim()}”.`;
  if (filter.value === "unavailable") return "Nothing is marked unavailable. All equipment is in service.";
  return "No equipment to show.";
});

async function load() {
  try {
    const { data } = await equipmentApi.listItems();
    items.value = data;
  } catch (e) {
    error.value = message(e, "Could not load equipment.");
  }
}

function pick(name) {
  newName.value = name;
  nameInput.value?.focus();
}

async function addItem() {
  clearMessages();
  const name = newName.value;
  const existing = items.value.find(
    (i) => i.name.trim().toLowerCase() === name.trim().toLowerCase()
  );
  if (existing) {
    filter.value = "all";
    startEdit(existing);
    error.value = `${existing.name} is already in the catalogue (${existing.totalQuantity} in total). Change its quantity below instead of adding it again.`;
    return;
  }
  try {
    await equipmentApi.createItem({ name, totalQuantity: newQuantity.value });
    success.value = `Added ${name}.`;
    newName.value = "";
    newQuantity.value = 1;
    await load();
    await nextTick();
    nameInput.value?.focus();
  } catch (e) {
    error.value = message(e, `Could not add ${name}. Please check the details and try again.`);
  }
}

function startEdit(item) {
  editingId.value = item.id;
  editQuantity.value = item.totalQuantity;
}

async function saveQuantity(item) {
  clearMessages();
  try {
    await equipmentApi.updateItem(item.id, { totalQuantity: editQuantity.value });
    editingId.value = null;
    success.value = `Updated ${item.name} to ${editQuantity.value}.`;
    await load();
  } catch (e) {
    error.value = message(e, `Could not update ${item.name}.`);
  }
}

async function markUnavailable(item, reason) {
  clearMessages();
  const label = REASONS.find((r) => r.value === reason)?.label.toLowerCase() || reason;
  const ok = await confirm(`Mark ${item.name} unavailable (${label})?`);
  if (!ok) return;
  try {
    const { data } = await equipmentApi.markUnavailable(item.id, reason);
    reportingId.value = null;
    const n = data.affectedReservations?.length || 0;
    if (n) warning.value = `${n} reservation(s) use ${item.name}. They were not cancelled, so please review them.`;
    await load();
  } catch (e) {
    error.value = message(e, `Could not mark ${item.name} unavailable.`);
  }
}

async function markActive(item) {
  clearMessages();
  try {
    await equipmentApi.markActive(item.id);
    await load();
  } catch (e) {
    error.value = message(e, `Could not restore ${item.name}.`);
  }
}

onMounted(load);
</script>

<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text, #2d2a4a); }
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); overflow: hidden; margin-bottom: 1rem; }
.add-form { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 0.75rem; padding: 0.85rem 1rem; }
.field { display: flex; flex-direction: column; gap: 0.25rem; font-size: 0.8rem; font-weight: 500; color: var(--text-muted, #6b6890); }
.field input { padding: 0.4rem 0.7rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; color: var(--text, #2d2a4a); min-width: 14rem; }
.field.qty input { min-width: 8rem; width: 8rem; }
.chips { flex-basis: 100%; display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem; }
.hint { font-size: 0.8rem; color: var(--text-muted, #6b6890); }
.chip { padding: 0.2rem 0.7rem; border: 1px solid var(--border, #e4defa); border-radius: 999px; background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0); font: inherit; font-size: 0.8rem; font-weight: 500; cursor: pointer; }
.chip:hover { background: #ddd6fb; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.75rem; }
.tabs { display: inline-flex; gap: 0.35rem; }
.tab { padding: 0.3rem 0.9rem; border: 1px solid var(--border, #e4defa); border-radius: 999px; background: #fff;
  color: var(--text-muted, #6b6890); font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; }
.tab.active { background: var(--primary, #6d5bd0); border-color: var(--primary, #6d5bd0); color: #fff; }
.tab-count { margin-left: 0.2rem; opacity: 0.8; }
.search { padding: 0.4rem 0.8rem; min-width: 16rem; border: 1px solid var(--border, #e4defa); border-radius: 999px; font: inherit; }
.table-wrap { overflow-x: auto; }
.items { width: 100%; border-collapse: collapse; text-align: left; }
.items th { padding: 0.65rem 1rem; background: #ddd6fb; font-size: 0.85rem; font-weight: 600; color: var(--lilac-text, #4b3fa0); white-space: nowrap; }
.items td { padding: 0.75rem 1rem; border-bottom: 1px solid var(--border, #e4defa); color: var(--text, #2d2a4a); }
.items tbody tr:last-child td { border-bottom: none; }
.items tbody tr:hover { background: #faf9ff; }
.items tbody tr.off .item-name { color: var(--text-muted, #6b6890); }
.item-name { font-weight: 500; }
.right { text-align: right; }
.item-actions { display: inline-flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; justify-content: flex-end; }
.edit { display: inline-flex; align-items: center; gap: 0.4rem; }
.edit input { width: 5.5rem; padding: 0.3rem 0.5rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; }
.link { border: none; background: none; padding: 0 0.25rem; color: var(--primary, #6d5bd0); font: inherit; font-size: 0.85rem; cursor: pointer; text-decoration: underline; }
.muted-link { color: var(--text-muted, #6b6890); }
.btn { padding: 0.4rem 1rem; border: none; border-radius: 999px; font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; }
.btn-primary { background: var(--primary, #6d5bd0); color: #fff; }
.btn-sky { background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); }
.btn-rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.warning { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: #fff3cd; color: #7a5d00; font-size: 0.9rem; }
.success { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--mint-bg, #d3f5e3);
  color: var(--mint-text, #1e6b47); font-size: 0.9rem; }
.empty { padding: 2rem 1rem; text-align: center; color: var(--text-muted, #6b6890); }
.empty p { margin: 0; }
</style>
<template>
  <div>
    <h2 class="page-title">Equipment Catalogue</h2>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="warning" class="warning">{{ warning }}</p>

    <form class="card add-form" @submit.prevent="addItem">
      <input v-model="newName" placeholder="Equipment name" required />
      <input v-model.number="newQuantity" type="number" min="0" placeholder="Total quantity" required />
      <button class="btn btn-primary" type="submit">Add item</button>
    </form>

    <div v-if="items.length" class="card">
      <ul class="item-list">
        <li v-for="item in items" :key="item.id">
          <span class="item-info">
            <span class="item-name">{{ item.name }}</span>
            <span class="item-qty">Total: {{ item.totalQuantity }}</span>
            <span :class="['badge', item.status === 'active' ? 'badge-ok' : 'badge-warn']">
              {{ item.status }}
            </span>
          </span>
          <span class="item-actions">
            <template v-if="item.status === 'active'">
              <select v-model="reasons[item.id]">
                <option value="damaged">Damaged</option>
                <option value="maintenance">Maintenance</option>
              </select>
              <button class="btn btn-rose" @click="markUnavailable(item)">Mark unavailable</button>
            </template>
            <button v-else class="btn btn-sky" @click="markActive(item)">Restore to service</button>
          </span>
        </li>
      </ul>
    </div>
    <div v-else class="card empty"><p>No equipment yet.</p></div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue";
import equipmentApi from "../api/equipment";
import { useConfirm } from "../composables/useConfirm";

const items = ref([]);
const error = ref("");
const warning = ref("");
const reasons = reactive({});
const newName = ref("");
const newQuantity = ref(1);
const { confirm } = useConfirm();

function message(e, fallback) {
  return e.response?.data?.error || fallback;
}

async function load() {
  try {
    const { data } = await equipmentApi.listItems();
    items.value = data;
    data.forEach((i) => { if (!reasons[i.id]) reasons[i.id] = "maintenance"; });
  } catch (e) {
    error.value = message(e, "Could not load equipment.");
  }
}

async function addItem() {
  error.value = "";
  try {
    await equipmentApi.createItem({ name: newName.value, totalQuantity: newQuantity.value });
    newName.value = "";
    newQuantity.value = 1;
    await load();
  } catch (e) {
    error.value = message(e, "Could not add this item (is the name already used?).");
  }
}

async function markUnavailable(item) {
  error.value = "";
  warning.value = "";
  const reason = reasons[item.id];
  const ok = await confirm(`Mark ${item.name} unavailable (${reason})?`);
  if (!ok) return;
  try {
    const { data } = await equipmentApi.markUnavailable(item.id, reason);
    const n = data.affectedReservations?.length || 0;
    if (n) warning.value = `${n} reservation(s) use ${item.name}. They were not cancelled, so please review them.`;
    await load();
  } catch (e) {
    error.value = message(e, `Could not mark ${item.name} unavailable.`);
  }
}

async function markActive(item) {
  error.value = "";
  warning.value = "";
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
.add-form { display: flex; flex-wrap: wrap; gap: 0.5rem; padding: 0.85rem 1rem; }
.add-form input { padding: 0.4rem 0.7rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; }
.item-list { list-style: none; margin: 0; padding: 0; }
.item-list li { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 0.75rem;
  padding: 0.85rem 1rem; border-bottom: 1px solid var(--border, #e4defa); }
.item-list li:last-child { border-bottom: none; }
.item-info { display: flex; align-items: center; gap: 0.75rem; }
.item-name { font-weight: 500; }
.item-qty { color: var(--text-muted, #6b6890); font-size: 0.9rem; }
.item-actions { display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500; }
.badge-ok { background: #d9f5e3; color: #1f7a45; }
.badge-warn { background: #ffe9c7; color: #8a5a00; }
.btn { padding: 0.4rem 1rem; border: none; border-radius: 999px; font: inherit; font-size: 0.9rem; font-weight: 500; cursor: pointer; }
.btn-primary { background: var(--primary, #6d5bd0); color: #fff; }
.btn-sky { background: var(--sky-bg, #d6ecff); color: var(--sky-text, #1f5f99); }
.btn-rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
.error { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--rose-bg, #ffdce3);
  color: var(--rose-text, #a12b47); font-size: 0.9rem; }
.warning { margin: 0 0 1rem; padding: 0.6rem 0.9rem; border-radius: 10px; background: #fff3cd; color: #7a5d00; font-size: 0.9rem; }
.empty { padding: 2rem 1rem; text-align: center; color: var(--text-muted, #6b6890); }
.empty p { margin: 0; }
</style>
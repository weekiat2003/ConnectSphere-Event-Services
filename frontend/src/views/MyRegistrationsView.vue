<template>
  <section>
    <h2 class="page-title">My registrations</h2>

    <p v-if="message" class="notice" role="status">{{ message }}</p>
    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="empty">Loading...</p>
    <p v-else-if="!items.length && !error" class="empty">
      You have not registered for any events yet.
      <router-link to="/attendee/events">Browse events</router-link>
    </p>

    <ul v-else class="list">
      <li v-for="r in items" :key="r.id" :class="['card', { past: r.status === 'withdrawn' }]">
        <div>
          <h3>
            <router-link v-if="r.event" :to="`/attendee/events/${r.event.id}`">{{ r.event.name }}</router-link>
            <span v-else>Event unavailable</span>
          </h3>
          <p v-if="r.event" class="meta">{{ [r.event.date, r.event.time].filter(Boolean).join(" at ") }}</p>
          <p class="status">
            <span :class="['badge', badge(r.status)]">{{ label(r) }}</span>
            <span v-if="r.event && ['cancelled', 'completed'].includes(r.event.status)" class="badge rose">
              Event {{ r.event.status }}
            </span>
          </p>
        </div>
        <button v-if="canWithdraw(r)" type="button" class="btn-danger" :disabled="busy" @click="withdraw(r)">
          Withdraw
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import registrationsApi from "../api/registrations";
import { useConfirm } from "../composables/useConfirm";

const { confirm } = useConfirm();
const items = ref([]);
const loading = ref(false);
const busy = ref(false);
const error = ref("");
const message = ref("");

const badge = (s) => ({ registered: "mint", waitlisted: "butter", withdrawn: "grey" })[s] || "grey";
const label = (r) =>
  r.status === "waitlisted" ? `Waiting list: position ${r.queuePosition}` : r.status[0].toUpperCase() + r.status.slice(1);
const canWithdraw = (r) => r.status !== "withdrawn" && r.event?.status === "confirmed";

async function load() {
  try {
    const { data } = await registrationsApi.mine();
    items.value = data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load your registrations.";
  }
}

async function withdraw(r) {
  const ok = await confirm(`Withdraw from "${r.event?.name}"?`);
  if (!ok) return;
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await registrationsApi.withdraw(r.id);
    message.value = "Your registration was withdrawn.";
  } catch (e) {
    error.value = e.response?.data?.error || "Could not withdraw.";
  } finally {
    await load();
    busy.value = false;
  }
}

onMounted(async () => {
  loading.value = true;
  await load();
  loading.value = false;
});
</script>

<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text); }
.list { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.8rem; }
.card { display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 1rem 1.25rem; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; }
.card.past { opacity: 0.65; }
.card h3 { margin: 0 0 0.3rem; font-size: 1.05rem; }
.meta { margin: 0.2rem 0; color: var(--text-muted); }
.status { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.4rem 0 0; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.82rem; font-weight: 500; }
.mint { background: var(--mint-bg); color: var(--mint-text); }
.butter { background: var(--butter-bg); color: var(--butter-text); }
.rose { background: var(--rose-bg); color: var(--rose-text); }
.grey { background: var(--border); color: var(--text-muted); }
.notice { padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--mint-bg); color: var(--mint-text); }
.field-error { color: #a12b47; }
.empty { padding: 1rem; color: var(--text-muted); }
.btn-danger { padding: 0.5rem 1.2rem; border: none; border-radius: 999px; background: var(--rose-bg); color: var(--rose-text); font: inherit; font-weight: 500; cursor: pointer; }
button:disabled { opacity: 0.6; cursor: not-allowed; }
a:focus-visible, button:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
</style>

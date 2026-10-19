<template>
  <section>
    <h2 class="page-title">Events open for registration</h2>

    <p v-if="error" class="field-error" role="alert">{{ error }}</p>
    <p v-if="loading" class="empty">Loading events...</p>
    <p v-else-if="!events.length && !error" class="empty">
      There are no events taking registrations right now. Please check back later.
    </p>

    <div v-else class="grid">
      <article v-for="e in events" :key="e.id" class="card">
        <h3>{{ e.name }}</h3>
        <p class="meta">{{ when(e) }}</p>
        <p v-if="e.venues.length" class="meta">{{ e.venues.join(", ") }}</p>
        <p class="status">
          <span :class="['badge', badgeClass(e)]">{{ availability(e) }}</span>
          <span v-if="e.myRegistration" class="badge lilac">You are {{ e.myRegistration.status }}</span>
        </p>
        <router-link class="btn-primary" :to="`/attendee/events/${e.id}`">View details</router-link>
      </article>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import registrationsApi from "../api/registrations";

const events = ref([]);
const loading = ref(false);
const error = ref("");

const when = (e) => [e.date, e.time].filter(Boolean).join(" at ") || "Date to be confirmed";

function availability(e) {
  if (!e.registrationOpen) return "Registration not open";
  if (e.placesRemaining === null) return "Places available";
  if (e.placesRemaining === 0) return "Full: waiting list open";
  return `${e.placesRemaining} place${e.placesRemaining === 1 ? "" : "s"} left`;
}
const badgeClass = (e) => (!e.registrationOpen ? "rose" : e.placesRemaining === 0 ? "butter" : "mint");

onMounted(async () => {
  loading.value = true;
  try {
    const { data } = await registrationsApi.listEvents();
    events.value = data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load events.";
  } finally {
    loading.value = false;
  }
});
</script>

<style scoped>
.page-title { margin: 0 0 1rem; font-size: 1.5rem; font-weight: 600; color: var(--text); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
.card { padding: 1.25rem 1.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); }
.card h3 { margin: 0 0 0.4rem; }
.meta { margin: 0.2rem 0; color: var(--text-muted); }
.status { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.7rem 0; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.82rem; font-weight: 500; }
.mint { background: var(--mint-bg); color: var(--mint-text); }
.rose { background: var(--rose-bg); color: var(--rose-text); }
.butter { background: var(--butter-bg); color: var(--butter-text); }
.lilac { background: var(--lilac-bg); color: var(--lilac-text); }
.btn-primary { display: inline-block; padding: 0.5rem 1.2rem; border-radius: 999px; background: var(--primary); color: #fff; text-decoration: none; font-weight: 500; }
.btn-primary:hover { background: var(--primary-hover); }
.field-error { color: #a12b47; }
.empty { padding: 1rem; color: var(--text-muted); }
</style>

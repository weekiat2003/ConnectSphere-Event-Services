<template>
  <div class="card denied" role="alert">
    <h2>Access denied</h2>
    <p>You don't have permission to view this page. It is only available to {{ audience }}.</p>
    <router-link to="/">Back to Dashboard</router-link>
  </div>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";

const ROLE_LABELS = {
  safety_officer: "Safety Officers",
  event_coordinator: "Event Coordinators",
  event_organiser: "Event Organisers",
  venue_staff: "Venue Staff",
  technical_support_staff: "Technical Support Staff",
};

const route = useRoute();
const audience = computed(() => {
  const roles = [route.query.roles || []].flat().filter(Boolean);
  const labels = roles.map((r) => ROLE_LABELS[r] || r);
  return labels.length ? labels.join(" or ") : "authorised users";
});
</script>

<style scoped>
.card {
  margin-top: 2rem;
  padding: 1.5rem;
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
}
h2 {
  margin: 0 0 0.5rem;
  color: var(--rose-text, #a12b47);
}
</style>

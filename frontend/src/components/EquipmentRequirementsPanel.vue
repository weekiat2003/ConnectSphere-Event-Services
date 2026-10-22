<template>
  <div class="card panel">
    <h3 class="section-title">Equipment Requirements</h3>
    <p v-if="!requirements?.length" class="empty">No equipment requirements recorded.</p>
    <table v-else class="req-table">
      <thead>
        <tr>
          <th>Type</th><th>Qty</th><th>Technical requirements</th><th>Status</th><th>Testing</th><th>Installation</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="req in requirements" :key="req.id">
          <td>{{ req.type }}</td>
          <td>{{ req.quantity }}</td>
          <td>{{ req.technicalNotes || "—" }}</td>
          <td>
            <span :class="['badge', badgeClass(req.status)]">{{ statusText(req.status) }}</span>
            <span v-if="req.needsRecheck" class="badge badge-warn">Needs recheck</span>
          </td>
          <td>{{ progressText(req.testingStatus) }}</td>
          <td>{{ progressText(req.installationStatus) }}</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
defineProps({ requirements: { type: Array, default: () => [] } });

const STATUS = { requested: "Requested", confirmed: "Reserved", unavailable: "Unavailable" };
const PROGRESS = { pending: "Pending", in_progress: "In progress", done: "Done" };

function statusText(s) { return STATUS[s] || s; }
function progressText(s) { return PROGRESS[s] || "—"; }
function badgeClass(s) {
  if (s === "confirmed") return "badge-ok";
  if (s === "unavailable") return "badge-bad";
  return "badge-neutral";
}
</script>

<style scoped>
.card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); padding: 1rem; margin-bottom: 1rem; }
.section-title { margin: 0 0 0.75rem; font-size: 1.1rem; font-weight: 600; }
.req-table { width: 100%; border-collapse: collapse; }
.req-table th, .req-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border, #e4defa); }
.req-table th { font-size: 0.8rem; color: var(--text-muted, #6b6890); font-weight: 500; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500; margin-right: 0.35rem; }
.badge-ok { background: #d9f5e3; color: #1f7a45; }
.badge-warn { background: #ffe9c7; color: #8a5a00; }
.badge-bad { background: #ffdce3; color: #a12b47; }
.badge-neutral { background: #ece8fb; color: #4b3fa0; }
.empty { color: var(--text-muted, #6b6890); margin: 0; }
</style>
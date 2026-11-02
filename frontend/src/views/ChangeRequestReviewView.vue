<template>
  <div>
    <h2 class="page-title">Change Requests to Review</h2>
    <p class="hint">
      Requests from Organisers on events assigned to you. Review each one, then process or reject it.
    </p>

    <p v-if="loadError" class="field-error">{{ loadError }}</p>

    <div v-if="queue.length" class="card">
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Event</th>
              <th>Organiser</th>
              <th>Type</th>
              <th>Submitted</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in queue" :key="row.id" :class="{ selected: detail?.request.id === row.id }">
              <td class="name">{{ row.eventName }}</td>
              <td>{{ row.organiserName || "—" }}</td>
              <td><span class="badge" :class="typeClass(row)">{{ typeLabel(row) }}</span></td>
              <td class="muted">{{ formatDate(row.createdAt) }}</td>
              <td class="action"><button class="review-link" @click="openRequest(row.id)">Review</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div v-else-if="!loadError" class="card empty">
      <p>No pending change requests for your events.</p>
    </div>

    <p v-if="detailError" class="field-error">{{ detailError }}</p>

    <section v-if="detail" class="card detail">
      <div class="card-header">
        <h3>{{ detail.event.name }}</h3>
        <button class="btn btn-grey" @click="detail = null">Close</button>
      </div>
      <p class="meta">
        <span class="badge" :class="typeClass(detail.request)">{{ typeLabel(detail.request) }}</span>
        Event status: {{ statusLabel(detail.event.status) }} ·
        Organiser: {{ detail.event.organiserName || "—" }} ·
        Submitted {{ formatDate(detail.request.createdAt) }}
      </p>
      <p><strong>Reason:</strong> {{ detail.request.reason }}</p>

      <p v-if="detail.request.requestType === 'withdrawal'" class="notice-inline">
        The organiser is asking for this event to be withdrawn. No field values are being changed.
      </p>
      <div v-else class="table-wrap">
        <table class="changes">
          <thead><tr><th>Field</th><th>Current</th><th>Proposed</th></tr></thead>
          <tbody>
            <tr v-for="change in detail.changes" :key="change.field">
              <td class="name">{{ labelFor(change.field) }}</td>
              <td class="muted">{{ formatValue(change.field, change.current) }}</td>
              <td>{{ formatValue(change.field, change.proposed) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="detail.request.isSignificant && detail.request.requestType !== 'withdrawal'">
        <h4>Arrangements that could be affected</h4>
        <ul v-if="detail.affectedArrangements.length">
          <li v-for="(item, index) in detail.affectedArrangements" :key="index">
            <template v-if="item.kind === 'venue_booking'">Venue booking: {{ venueName(item.venueId) }}</template>
            <template v-else>Equipment: {{ item.quantity }} × {{ item.type }}</template>
            ({{ item.status }})
          </li>
        </ul>
        <p v-else class="notice-inline">No venue bookings or equipment are currently arranged for this event.</p>
      </div>

      <div v-if="detail.reReview" class="re-review">
        <h4>Re-review</h4>
        <p>
          Triggered by <strong>{{ detail.reReview.triggeredBy || "—" }}</strong>
          on {{ formatDate(detail.reReview.triggeredAt) }}.
        </p>

        <p v-if="detail.reReview.flaggedArrangements.length">
          The following arrangements were flagged as needing reconsideration:
        </p>
        <ul v-if="detail.reReview.flaggedArrangements.length">
          <li v-for="(item, index) in detail.reReview.flaggedArrangements" :key="index">
            <template v-if="item.kind === 'venue_booking'">
              Venue booking: {{ venueName(item.venueId) }} ({{ item.status }})
            </template>
            <template v-else>
              Equipment: {{ item.quantity }} × {{ item.type }} ({{ item.status }})
            </template>
            —
            <strong>{{ item.needsReconsideration ? "Needs reconsideration" : "Cleared" }}</strong>
          </li>
        </ul>
        <p v-else class="notice-inline">No arrangements needed reconsideration.</p>
      </div>

      <div v-if="detail.decision" class="decision">
        <strong>{{ statusLabel(detail.decision.status) }}</strong>
        by {{ detail.decision.decidedBy || "—" }} on {{ formatDate(detail.decision.decidedAt) }}
        <p v-if="detail.decision.reason"><strong>Reason:</strong> {{ detail.decision.reason }}</p>
      </div>
      <div v-else class="actions">
        <button
          v-for="action in detail.availableActions"
          :key="action"
          class="btn"
          :class="actionClass(action)"
          :disabled="processing"
          @click="runAction(action)"
        >
          {{ ACTION_LABELS[action] }}
        </button>
      </div>
      <div v-if="showRejectForm && !detail.decision" class="reject-form">
        <label>
          Reason for rejecting
          <textarea v-model="rejectReason" placeholder="Explain why this change cannot go ahead"></textarea>
        </label>
        <div class="actions">
          <button class="btn btn-rose" :disabled="processing" @click="rejectChange">Confirm rejection</button>
          <button class="btn btn-grey" :disabled="processing" @click="showRejectForm = false">Back</button>
        </div>
      </div>
      <p v-if="actionError" class="field-error">{{ actionError }}</p>
      <ul v-if="Object.keys(actionErrors).length" class="field-error">
        <li v-for="(message, field) in actionErrors" :key="field">
          {{ field === "request" || field === "event" ? "" : labelFor(field) + ": " }}{{ message }}
        </li>
      </ul>
    </section>
  </div>
</template>
  
  <script setup>
  import { onMounted, ref } from "vue";
  import { useRoute, useRouter } from "vue-router";
  import changeRequestsApi from "../api/changeRequests";
  import { useConfirm } from "../composables/useConfirm";
  
  const route = useRoute();
  const router = useRouter();
  const queue = ref([]);
  const detail = ref(null);
  const venues = ref([]);
  const loadError = ref("");
  const detailError = ref("");
  const { confirm } = useConfirm();
  const processing = ref(false);
  const actionError = ref("");
  const actionErrors = ref({});
  const showRejectForm = ref(false);
  const rejectReason = ref("");
  
  const FIELD_LABELS = {
    proposed_date: "Date",
    proposed_time: "Time",
    expected_attendance: "Expected attendance",
    capacity_needed: "Venue capacity needed",
    required_layout: "Required layout",
    required_facilities: "Required facilities",
    accessibility_needs: "Accessibility needs",
    registration_required: "Registration required",
    intended_capacity: "Intended capacity",
    name: "Event name",
    purpose: "Purpose",
    description: "Description",
    category: "Category",
    venue_id: "Venue",
    equipment_requirements: "Equipment",
    process_change: "Process change",
    trigger_re_review: "Trigger re-review",
    apply_change: "Record change is going ahead",
    reject_change: "Reject",
    cancel_event: "Cancel event",
  };
  const ACTION_LABELS = {
    process_change: "Process change",
    trigger_re_review: "Trigger re-review",
    apply_change: "Record change is going ahead",
    reject_change: "Reject",
    cancel_event: "Cancel event",
};
  
  const labelFor = (field) => FIELD_LABELS[field] || field;
  const statusLabel = (value) => String(value || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
  const formatDate = (iso) => (iso ? new Date(iso).toLocaleString() : "—");
  const venueName = (id) => venues.value.find((v) => v.id === id)?.name || `Venue #${id}`;
  
  function typeLabel(row) {
    if (row.requestType === "withdrawal") return "Withdrawal";
    return row.isSignificant ? "Significant" : "Routine";
  }
  function typeClass(row) {
    if (row.requestType === "withdrawal") return "withdrawal";
    return row.isSignificant ? "significant" : "routine";
  }
  
  function formatValue(field, value) {
    if (value === null || value === undefined || value === "") return "—";
    if (field === "venue_id") return venueName(value);
    if (field === "equipment_requirements") {
      return value.length ? value.map((i) => `${i.quantity} × ${i.type}`).join(", ") : "None";
    }
    if (field === "proposed_time") return String(value).slice(0, 5);
    if (typeof value === "boolean") return value ? "Yes" : "No";
    return Array.isArray(value) ? value.join(", ") : String(value);
  }
  
  async function ensureVenues() {
    if (venues.value.length) return;
    try {
      const { data } = await changeRequestsApi.getCatalogue();
      venues.value = data.venues || [];
    } catch (e) {
      venues.value = [];
    }
  }
  
  async function loadQueue() {
    loadError.value = "";
    try {
      const { data } = await changeRequestsApi.getReviewQueue();
      queue.value = data;
    } catch (e) {
      loadError.value = e.response?.data?.error || "Could not load the change requests.";
    }
  }
  
  async function openRequest(id) {
    detailError.value = "";
    try {
      await ensureVenues();
      const { data } = await changeRequestsApi.getReviewDetail(id);
      detail.value = data;
    } catch (e) {
      detail.value = null;
      detailError.value = e.response?.data?.error || "Could not open this change request.";
    }
  }

  async function processChange() {
    actionError.value = "";
    actionErrors.value = {};
    const id = detail.value.request.id;
    processing.value = true;
    try {
      try {
        await changeRequestsApi.processChange(id); // not confirmed yet: the server answers 409 with its message
      } catch (e) {
        if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
          if (!(await confirm(e.response.data.message))) return;
          await changeRequestsApi.processChange(id, true);
        } else {
          throw e;
        }
      }
      await loadQueue();
      await openRequest(id); // shows the decision, who made it and when
    } catch (e) {
      const data = e.response?.data;
      actionError.value = data?.errors ? "" : data?.error || "Could not process this change request.";
      actionErrors.value = data?.errors || {};
    } finally {
      processing.value = false;
    }
  }

  function actionClass(action) {
    if (action === "trigger_re_review") return "btn-butter";
    if (action === "apply_change") return "btn-mint";
    if (action === "cancel_event" || action === "reject_change") return "btn-rose";
    return "btn-primary";
  }

  async function runAction(action) {
  if (action === "process_change") return processChange();
  if (action === "trigger_re_review") return triggerReReview();
  if (action === "apply_change") return applyReReview();
  if (action === "cancel_event") {
    return router.push({
      name: "event-detail",
      params: { id: detail.value.event.id },
      query: { cancel: "1", fromRequest: detail.value.request.id },
    });
  }
  if (action === "reject_change") {
    actionError.value = "";
    actionErrors.value = {};
    showRejectForm.value = true;
  }
}

  async function rejectChange() {
  actionError.value = "";
  actionErrors.value = {};
  const id = detail.value.request.id;
  processing.value = true;
  try {
    try {
      await changeRequestsApi.rejectChange(id, rejectReason.value);
    } catch (e) {
      if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
        if (!(await confirm(e.response.data.message))) return;
        await changeRequestsApi.rejectChange(id, rejectReason.value, true);
      } else {
        throw e;
      }
    }
    showRejectForm.value = false;
    rejectReason.value = "";
    await loadQueue();
    await openRequest(id); // shows the rejection, who made it and when
  } catch (e) {
    const data = e.response?.data;
    actionError.value = data?.errors ? "" : data?.error || "Could not reject this change request.";
    actionErrors.value = data?.errors || {};
  } finally {
    processing.value = false;
  }
}

  async function triggerReReview() {
    actionError.value = "";
    actionErrors.value = {};
    const id = detail.value.request.id;
    processing.value = true;

    try {
      try {
        await changeRequestsApi.startReReview(id);
      } catch (e) {
        if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
          if (!(await confirm(e.response.data.message))) return;
          await changeRequestsApi.startReReview(id, true);
        } else {
          throw e;
        }
      }

      await loadQueue();
      await openRequest(id);
    } catch (e) {
      const data = e.response?.data;
      actionError.value = data?.errors ? "" : data?.error || "Could not trigger re-review.";
      actionErrors.value = data?.errors || {};
    } finally {
      processing.value = false;
    }
  }

  async function applyReReview() {
  if (processing.value) return;
  actionError.value = "";
  actionErrors.value = {};
  const id = detail.value.request.id;
  processing.value = true;

  try {
    try {
      await changeRequestsApi.applyReReview(id);
    } catch (e) {
      if (e.response?.status === 409 && e.response.data?.requiresConfirmation) {
        const ok = await confirm(e.response.data.message);
        if (!ok) return;
        await changeRequestsApi.applyReReview(id, true);
      } else {
        throw e;
      }
    }

    await loadQueue();
    await openRequest(id);
  } catch (e) {
    const data = e.response?.data;
    if (data?.errors?.request) {
      // Already recorded (e.g. repeated call): show the current state instead of an error.
      await loadQueue();
      await openRequest(id);
      return;
    }
    actionError.value =
      data?.error ||
      (data?.errors ? Object.values(data.errors).join(" ") : "") ||
      "Could not record the change as going ahead.";
    actionErrors.value = data?.errors || {};
  } finally {
    processing.value = false;
  }
}
  
  onMounted(async () => {
    await loadQueue();
    if (route.query.id) await openRequest(Number(route.query.id)); // lets a decided request be opened by link
  });
  </script>
  
  <style scoped>
  .page-title {
    margin: 0 0 0.5rem;
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--text, #2d2a4a);
  }
  .hint {
    margin: 0 0 1rem;
    color: var(--text-muted, #6b6890);
    font-size: 0.9rem;
  }
  .card {
    background: var(--surface, #fff);
    border: 1px solid var(--border, #e4defa);
    border-radius: 14px;
    box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
    overflow: hidden;
  }
  .card.empty {
    padding: 2rem 1rem;
    text-align: center;
    color: var(--text-muted, #6b6890);
  }
  .card.empty p {
    margin: 0;
  }
  .card.detail {
    margin-top: 1rem;
    padding: 1.25rem 1.5rem;
  }
  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .card-header h3 {
    margin: 0;
  }
  .table-wrap {
    overflow-x: auto;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    text-align: left;
  }
  th {
    padding: 0.75rem 1rem;
    background: #ddd6fb;
    border-bottom: 1px solid var(--border, #e4defa);
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--lilac-text, #4b3fa0);
    white-space: nowrap;
  }
  td {
    padding: 0.85rem 1rem;
    border-bottom: 1px solid var(--border, #e4defa);
    color: var(--text, #2d2a4a);
  }
  tbody tr:last-child td {
    border-bottom: none;
  }
  tbody tr:hover {
    background: #faf9ff;
  }
  tr.selected {
    background: #f3f1ff;
  }
  .name {
    font-weight: 500;
  }
  .muted {
    color: var(--text-muted, #6b6890);
  }
  .action {
    text-align: right;
  }
  .review-link {
    display: inline-block;
    padding: 0.3rem 0.9rem;
    border: none;
    border-radius: 999px;
    background: var(--primary-tint, #ebe7ff);
    color: var(--primary, #6d5bd0);
    font: inherit;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
  }
  .review-link:hover {
    background: var(--primary, #6d5bd0);
    color: #ffffff;
  }
  .review-link:focus-visible,
  .btn:focus-visible {
    outline: 2px solid var(--primary, #6d5bd0);
    outline-offset: 2px;
  }
  .meta {
    color: var(--text-muted, #6b6890);
    font-size: 0.9rem;
  }
  .notice-inline {
    margin: 0.5rem 0;
    font-size: 0.9rem;
    color: var(--text-muted, #6b6890);
  }
  .field-error {
    color: var(--rose-text, #a12b47);
    font-size: 0.85rem;
  }
  .badge {
    display: inline-block;
    padding: 0.15rem 0.65rem;
    border-radius: 999px;
    background: var(--lilac-bg, #e9e5fb);
    color: var(--lilac-text, #4b3fa0);
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
  }
  .badge.significant,
  .badge.withdrawal {
    background: var(--rose-bg, #ffdce3);
    color: var(--rose-text, #a12b47);
  }
  .badge.routine {
    background: var(--sky-bg, #d6ecff);
    color: var(--sky-text, #1f5f99);
  }
  .re-review {
    margin-top: 1rem;
    padding: 0.85rem 1rem;
    border-radius: 12px;
    background: var(--butter-bg, #fff1c2);
    color: var(--butter-text, #8a5a00);
  }
  .decision {
    margin-top: 1rem;
    padding: 0.85rem 1rem;
    border-radius: 12px;
    background: var(--sky-bg, #d6ecff);
    color: var(--sky-text, #1f5f99);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-top: 1rem;
  }
  .reject-form {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 1rem;
  }
  .reject-form label {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    font-size: 0.9rem;
    font-weight: 500;
  }
  textarea {
    min-height: 4.5rem;
    padding: 0.6rem 0.75rem;
    border: 1px solid var(--border, #e4defa);
    border-radius: 10px;
    background: #fcfbff;
    color: var(--text, #2d2a4a);
    font: inherit;
    resize: vertical;
  }
  textarea:focus {
    outline: none;
    border-color: var(--primary, #6d5bd0);
    background: #ffffff;
    box-shadow: 0 0 0 3px var(--primary-tint, #ebe7ff);
  }
  
  /* Buttons: colour matches meaning, same as event detail page */
  .btn {
    padding: 0.5rem 1.1rem;
    border: none;
    border-radius: 999px;
    font: inherit;
    font-size: 0.9rem;
    font-weight: 500;
    cursor: pointer;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn-primary { background: var(--primary, #6d5bd0); color: #ffffff; }
  .btn-primary:hover { background: var(--primary-hover, #5b49bd); }
  .btn-mint { background: var(--mint-bg, #d3f5e3); color: var(--mint-text, #1e6b47); }
  .btn-mint:hover { background: #bdeed3; }
  .btn-rose { background: var(--rose-bg, #ffdce3); color: var(--rose-text, #a12b47); }
  .btn-rose:hover { background: #ffc9d4; }
  .btn-butter { background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
  .btn-butter:hover { background: #ffe8a0; }
  .btn-grey { background: #c6cfd7; color: #626364; }
  .btn-grey:hover { background: #b0b3b6; }
  </style>
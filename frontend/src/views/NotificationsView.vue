<template>
  <div>
    <div class="header">
      <h2 class="page-title">Notifications</h2>
      <div class="controls">
        <label>
          <input v-model="unreadOnly" type="checkbox" @change="load" />
          Unread only
        </label>
        <button class="btn" :disabled="!hasUnread" @click="markAll">Mark all as read</button>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <ul v-if="items.length" class="list">
      <li v-for="n in items" :key="n.id" :class="['item', { unread: !n.isRead, cleared: n.isCleared }]">
        <div class="body">
          <span class="tag">{{ TYPE_LABELS[n.type] || "Update" }}</span>
          <strong>{{ n.title }}</strong>
          <span v-if="n.eventName" class="event-name">{{ n.eventName }}</span>
          <p>{{ n.message }}</p>
          <p v-if="n.isCleared && n.data.assignedTo" class="assigned">Assigned to {{ n.data.assignedTo }}</p>
          <small>{{ formatTimestamp(n.createdAt) }}</small>
        </div>
        <div class="actions">
          <button v-if="n.link" class="btn" @click="open(n)">View</button>
          <button v-if="!n.isRead" class="btn" @click="markOne(n)">Mark read</button>
        </div>
      </li>
    </ul>

    <div v-else-if="!loading" class="card empty">
      <p>{{ unreadOnly ? "No unread notifications." : "You have no notifications yet." }}</p>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import notificationsApi from "../api/notifications";
import { formatTimestamp } from "../utils/display";

const TYPE_LABELS = {
  organiser_update: "Your request",
  new_event_submission: "Assignment queue",
  coordinator_assignment: "Assignment",
  reassignment_request: "Reassignment",
  venue_booking_update: "Venue booking",
  new_venue_booking_request: "Booking request",
  new_equipment_request: "Equipment",
  registration_change: "Registration",
  safety_check: "Safety check",
};

const items = ref([]);
const unreadOnly = ref(false);
const loading = ref(false);
const error = ref("");
const router = useRouter();

const hasUnread = computed(() => items.value.some((n) => !n.isRead));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const { data } = await notificationsApi.list({ unread: unreadOnly.value });
    items.value = data;
  } catch (e) {
    error.value = e.response?.data?.error || "Could not load notifications.";
  } finally {
    loading.value = false;
  }
}

async function markOne(n) {
  try {
    await notificationsApi.markRead(n.id);
    n.isRead = true;
    if (unreadOnly.value) items.value = items.value.filter((x) => x.id !== n.id);
  } catch (e) {
    error.value = e.response?.data?.error || "Could not update the notification.";
  }
}

async function markAll() {
  try {
    await notificationsApi.markAllRead();
    await load();
  } catch (e) {
    error.value = e.response?.data?.error || "Could not update notifications.";
  }
}

async function open(n) {
  if (!n.isRead) await markOne(n);
  router.push(n.link);
}

onMounted(load);
</script>

<style scoped>
.header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  justify-content: space-between;
}

.controls {
  display: flex;
  gap: 0.75rem;
  align-items: center;
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 0.5rem;
}

.item,
.card {
  display: flex;
  gap: 1rem;
  justify-content: space-between;
  padding: 0.85rem 1rem;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: var(--surface);
}

.item.unread {
  border-left: 4px solid var(--primary);
  background: var(--primary-tint);
}

.item.cleared {
  opacity: 0.75;
}

.tag {
  display: inline-block;
  margin-right: 0.5rem;
  padding: 0 0.5rem;
  border-radius: 999px;
  background: var(--sky-bg);
  color: var(--sky-text);
  font-size: 0.75rem;
  font-weight: 600;
}

.event-name {
  display: block;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.assigned {
  color: var(--mint-text);
  font-weight: 600;
}

.body p {
  margin: 0.25rem 0;
}

.body small {
  color: var(--text-muted);
}

.actions {
  display: flex;
  gap: 0.4rem;
  align-items: flex-start;
}

.btn {
  padding: 0.35rem 0.8rem;
  border: none;
  border-radius: 999px;
  background: var(--lilac-bg);
  color: var(--lilac-text);
  font: inherit;
}

.btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.error {
  color: var(--rose-text);
}
</style>

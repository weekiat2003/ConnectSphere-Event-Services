<template>
  <section>
    <router-link to="/attendee/events" class="back">Back to events</router-link>

    <p v-if="loading" class="empty">Loading...</p>
    <div v-else-if="notFound" class="card" role="alert">
      <h2 class="page-title">Event not found</h2>
      <p>This event does not exist or is not open to you.</p>
    </div>

    <div v-else-if="event" class="card">
      <h2 class="page-title">{{ event.name }}</h2>
      <p class="meta">{{ when }}</p>
      <p v-if="event.venues.length" class="meta">Venue: {{ event.venues.join(", ") }}</p>
      <p v-if="event.description" class="desc">{{ event.description }}</p>

      <p class="status">
        <span class="badge lilac">{{ event.statusLabel }}</span>
        <span :class="['badge', event.registrationOpen ? 'mint' : 'rose']">
          {{ event.registrationOpen ? "Registration open" : "Registration not open" }}
        </span>
        <span v-if="event.capacity !== null" :class="['badge', event.isFull ? 'butter' : 'sky']">
          {{ event.isFull ? "Full" : `${event.placesRemaining} of ${event.capacity} places left` }}
        </span>
      </p>

      <p v-if="message" class="notice" role="status">{{ message }}</p>
      <p v-if="error" class="field-error" role="alert">{{ error }}</p>

      <div v-if="event.myRegistration" class="mine">
        <p>
          <strong>You are {{ event.myRegistration.status }}.</strong>
          <span v-if="event.myRegistration.queuePosition"> Your place in the waiting list: {{ event.myRegistration.queuePosition }}.</span>
        </p>
        <button v-if="canWithdraw" type="button" class="btn-danger" :disabled="busy" @click="withdraw">
          Withdraw
        </button>
      </div>

      <div v-else class="actions">
        <button v-if="event.canRegister" type="button" class="btn-primary" :disabled="busy" @click="register">
          Register
        </button>
        <button v-if="event.canJoinWaitlist" type="button" class="btn-primary" :disabled="busy" @click="joinWaitlist">
          Join the waiting list
        </button>
        <p v-if="!event.canRegister && !event.canJoinWaitlist" class="meta">{{ whyNot }}</p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import registrationsApi from "../api/registrations";
import { useConfirm } from "../composables/useConfirm";

const route = useRoute();
const { confirm } = useConfirm();
const event = ref(null);
const loading = ref(false);
const notFound = ref(false);
const busy = ref(false);
const error = ref("");
const message = ref("");

const when = computed(() => [event.value.date, event.value.time].filter(Boolean).join(" at ") || "Date to be confirmed");
const canWithdraw = computed(() => event.value.status === "confirmed");
const whyNot = computed(() => {
  if (["cancelled", "completed"].includes(event.value.status)) return `This event is ${event.value.status}. Registration is no longer possible.`;
  if (!event.value.registrationOpen) return "Registration is not open for this event.";
  return "";
});

async function load() {
  try {
    const { data } = await registrationsApi.getEvent(route.params.id);
    event.value = data;
    notFound.value = false;
  } catch (e) {
    if (e.response?.status === 404) notFound.value = true;
    else error.value = e.response?.data?.error || "Could not load the event.";
  }
}

async function run(action, okMessage) {
  busy.value = true;
  error.value = "";
  message.value = "";
  try {
    await action();
    message.value = okMessage;
  } catch (e) {
    error.value = e.response?.data?.error || "Something went wrong. Please try again.";
  } finally {
    await load();
    busy.value = false;
  }
}

const register = () => run(() => registrationsApi.register(event.value.id), "You are registered.");
const joinWaitlist = () => run(() => registrationsApi.joinWaitlist(event.value.id), "You have joined the waiting list.");

async function withdraw() {
  const ok = await confirm("Withdraw your registration? Your place will be given to the next person.");
  if (!ok) return;
  await run(() => registrationsApi.withdraw(event.value.myRegistration.id), "Your registration was withdrawn.");
}

onMounted(async () => {
  loading.value = true;
  await load();
  loading.value = false;
});
</script>

<style scoped>
.back { display: inline-block; margin-bottom: 1rem; color: var(--primary); }
.page-title { margin: 0 0 0.5rem; font-size: 1.5rem; font-weight: 600; color: var(--text); }
.card { padding: 1.25rem 1.5rem; background: var(--surface); border: 1px solid var(--border); border-radius: 14px; box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); }
.meta { margin: 0.2rem 0; color: var(--text-muted); }
.desc { margin: 0.8rem 0; }
.status { display: flex; gap: 0.4rem; flex-wrap: wrap; margin: 0.8rem 0; }
.badge { padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.82rem; font-weight: 500; }
.mint { background: var(--mint-bg); color: var(--mint-text); }
.rose { background: var(--rose-bg); color: var(--rose-text); }
.butter { background: var(--butter-bg); color: var(--butter-text); }
.sky { background: var(--sky-bg); color: var(--sky-text); }
.lilac { background: var(--lilac-bg); color: var(--lilac-text); }
.notice { padding: 0.6rem 0.9rem; border-radius: 10px; background: var(--mint-bg); color: var(--mint-text); }
.field-error { color: #a12b47; }
.empty { padding: 1rem; color: var(--text-muted); }
.actions, .mine { margin-top: 1rem; display: flex; gap: 0.6rem; flex-wrap: wrap; align-items: center; }
.btn-primary, .btn-danger { padding: 0.5rem 1.2rem; border: none; border-radius: 999px; font: inherit; font-weight: 500; cursor: pointer; }
.btn-primary { background: var(--primary); color: #fff; }
.btn-primary:hover { background: var(--primary-hover); }
.btn-danger { background: var(--rose-bg); color: var(--rose-text); }
button:disabled { opacity: 0.6; cursor: not-allowed; }
button:focus-visible, a:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
</style>


<template>
  <section>
    <div class="head">
      <h2 class="page-title">Venue Booking Approval</h2>
      <button
        type="button"
        class="btn-primary"
        :disabled="loading"
        @click="refreshBookings"
      >
        {{ loading ? "Refreshing..." : "Refresh requests" }}
      </button>
    </div>

    <p class="intro">
      Review pending requests, manage tentative holds, and manage approved bookings for venues you own.
    </p>

    <div class="booking-tabs" role="tablist" aria-label="Booking status">
      <button type="button" role="tab" :aria-selected="activeTab === 'pending'"
        :class="['booking-tab', { active: activeTab === 'pending' }]"
        @click="switchBookingTab('pending')">Pending Requests</button>
      <button type="button" role="tab" :aria-selected="activeTab === 'approved'"
        :class="['booking-tab', { active: activeTab === 'approved' }]"
        @click="switchBookingTab('approved')">Approved Bookings</button>
    </div>

    <p v-if="error" class="field-error" role="alert">
      {{ error }}
    </p>

    <p v-if="notice" class="success" role="status">
      {{ notice }}
    </p>

    <p v-if="loading" class="empty" role="status">
      Loading {{ activeTab }} bookings...
    </p>

    <p v-else-if="!error && !displayedBookings.length" class="empty">
      {{ activeTab === "pending" ? "No pending booking requests for your venues." : "No approved bookings for your venues." }}
    </p>

    <template v-else-if="!error && !loading">
      <div class="card summary">
        <span class="summary-label">{{ activeTab === "pending" ? "Pending booking requests" : "Approved bookings" }}</span>
        <span class="badge cap">
          {{ displayedBookings.length }}
          {{ displayedBookings.length === 1 ? "request" : "requests" }}
        </span>
      </div>

      <div class="grid" aria-live="polite">
        <article
          v-for="booking in displayedBookings"
          :key="booking.id"
          class="card booking"
        >
          <header>
            <h3>
              {{ booking.eventName || `Event #${booking.eventId}` }}
            </h3>
            <span class="badge cap">{{ booking.status === "held" ? "Held" : booking.status === "approved" ? "Approved" : "Pending" }}</span>
          </header>

          <p class="meta">Request #{{ booking.id }}</p>

          <p class="meta">
            <strong>Venue:</strong>
            {{ booking.venueName || `Venue #${booking.venueId}` }}
          </p>

          <p class="meta">
            <strong>Location:</strong>
            {{ booking.venueLocation || "Not specified" }}
          </p>

          <p class="meta">
            <strong>Event date:</strong>
            {{ formatDate(booking.startDatetime) }}
          </p>

          <p class="meta">
            <strong>Time:</strong>
            {{ formatTime(booking.startDatetime) }}
            –
            {{ formatTime(booking.endDatetime) }}
          </p>

          <div class="chips">
            <span class="badge sky">
              {{ booking.expectedAttendance ?? "Unknown" }} attendees
            </span>
            <span class="badge lilac">
              Submitted {{ formatDate(booking.createdAt) }}
            </span>
          </div>

          <p v-if="booking.eventDescription" class="desc">
            {{ booking.eventDescription }}
          </p>

          <p v-if="booking.status === 'held'" class="hold-info">Tentative hold until {{ formatHoldExpiry(booking.holdExpiresAt) }}</p>
          <div v-if="activeTab === 'pending'" class="booking-decision-actions">
            <button v-if="booking.status === 'pending'" type="button" class="btn-ghost" @click="openHold(booking, 'place')">Place hold</button>
            <button v-if="booking.status === 'held'" type="button" class="btn-ghost" @click="openHold(booking, 'extend')">Extend hold</button>
            <button v-if="booking.status === 'held'" type="button" class="btn-danger" @click="openReleaseConfirmation(booking)">Release hold</button>
          <button
            type="button"
            class="btn-ghost approve-btn"
            :disabled="approvingId !== null || rejectingId !== null"
            @click="openApprovalConfirmation(booking)"
          >
            {{ approvingId === booking.id ? "Approving..." : "Approve booking" }}
          </button>
          <button v-if="booking.status === 'pending'" type="button" class="btn-danger reject-btn"
            :disabled="approvingId !== null || rejectingId !== null"
            @click="openRejectionConfirmation(booking)">
            {{ rejectingId === booking.id ? "Rejecting..." : "Reject booking" }}
          </button>
          </div>
          <div v-if="activeTab === 'approved'" class="booking-decision-actions">
            <button type="button" class="btn-danger reject-btn"
              :disabled="cancellingId !== null" @click="openCancellationConfirmation(booking)">
              {{ cancellingId === booking.id ? "Cancelling..." : "Cancel booking" }}
            </button>
          </div>
        </article>
      </div>
    </template>

    <div v-if="holdBooking" class="modal-backdrop" @click.self="holdBooking = null">
      <div class="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="hold-title">
        <h3 id="hold-title">{{ holdAction === 'place' ? 'Place tentative hold' : 'Extend tentative hold' }}</h3>
        <p>Choose a future expiry for {{ holdBooking.venueName }}.</p>
        <label for="hold-expiry">Expiry date and time</label>
        <input id="hold-expiry" type="datetime-local" v-model="holdExpiry" />
        <p v-if="holdError" class="field-error" role="alert">{{ holdError }}</p>
        <div class="confirmation-actions">
          <button type="button" class="btn-primary secondary" @click="holdBooking = null">Cancel</button>
          <button type="button" class="btn-primary" :disabled="holdSaving" @click="saveHold">{{ holdSaving ? 'Saving...' : 'Save hold' }}</button>
        </div>
      </div>
    </div>
    <!-- Cancellation confirmation for an already approved booking -->
    <div v-if="bookingToCancel" class="modal-backdrop" @click.self="closeCancellation">
      <div class="confirmation-dialog rejection-dialog" role="dialog" aria-modal="true"
        aria-labelledby="cancel-dialog-title">
        <h3 id="cancel-dialog-title">Cancel approved booking?</h3>
        <p>This will cancel the approved booking for
          <strong>{{ bookingToCancel.eventName || `Event #${bookingToCancel.eventId}` }}</strong>
          at <strong>{{ bookingToCancel.venueName || `Venue #${bookingToCancel.venueId}` }}</strong>.
          The Event Coordinator will see the cancelled status.</p>
        <p class="dialog-time">
          <strong>Start:</strong> {{ formatDate(bookingToCancel.startDatetime) }} {{ formatTime(bookingToCancel.startDatetime) }}
          <br />
          <strong>End:</strong> {{ formatDate(bookingToCancel.endDatetime) }} {{ formatTime(bookingToCancel.endDatetime) }}
        </p>
        <label class="rejection-label" for="cancellation-reason">Cancellation reason (optional)</label>
        <textarea id="cancellation-reason" v-model="cancellationReason" rows="3"
          placeholder="e.g. Venue unavailable due to urgent maintenance"
          :aria-invalid="cancellationReason.length > REJECTION_LIMIT" />
        <p class="character-count" :class="{ 'over-limit': cancellationReason.length > REJECTION_LIMIT }">
          {{ cancellationReason.length }}/{{ REJECTION_LIMIT }} characters
        </p>
        <p v-if="cancellationError" class="field-error" role="alert">{{ cancellationError }}</p>
        <div class="confirmation-actions">
          <button type="button" class="btn-primary secondary" :disabled="cancellingId !== null"
            @click="closeCancellation">Keep booking</button>
          <button type="button" class="btn-danger reject-btn"
            :disabled="cancellingId !== null || cancellationReason.length > REJECTION_LIMIT"
            @click="confirmCancellation">
            {{ cancellingId !== null ? "Cancelling..." : "Yes, Cancel Booking" }}
          </button>
        </div>
      </div>
    </div>

    <!-- Rejection confirmation pop-up -->
    <div v-if="bookingToReject" class="modal-backdrop" @click.self="cancelRejection">
      <div class="confirmation-dialog rejection-dialog" role="dialog" aria-modal="true"
        aria-labelledby="reject-dialog-title" aria-describedby="reject-dialog-description">
        <h3 id="reject-dialog-title">Reject booking request?</h3>
        <p id="reject-dialog-description">
          Reject the request for
          <strong>{{ bookingToReject.eventName || `Event #${bookingToReject.eventId}` }}</strong>
          at <strong>{{ bookingToReject.venueName || `Venue #${bookingToReject.venueId}` }}</strong>?
          Both fields below are optional.
        </p>
        <p class="dialog-time">
          <strong>Start:</strong> {{ formatDate(bookingToReject.startDatetime) }} {{ formatTime(bookingToReject.startDatetime) }}
          <br />
          <strong>End:</strong> {{ formatDate(bookingToReject.endDatetime) }} {{ formatTime(bookingToReject.endDatetime) }}
        </p>
        <label class="rejection-label" for="rejection-reason">Reason for rejection (optional)</label>
        <textarea id="rejection-reason" v-model="rejectionReason" rows="3"
          placeholder="e.g. Venue unavailable due to maintenance"
          :aria-invalid="rejectionReason.length > REJECTION_LIMIT" />
        <p class="character-count" :class="{ 'over-limit': rejectionReason.length > REJECTION_LIMIT }">
          {{ rejectionReason.length }}/{{ REJECTION_LIMIT }} characters
        </p>
        <label class="rejection-label" for="rejection-alternative">Alternative suggestion (optional)</label>
        <textarea id="rejection-alternative" v-model="rejectionAlternative" rows="3"
          placeholder="e.g. Consider another date or venue"
          :aria-invalid="rejectionAlternative.length > REJECTION_LIMIT" />
        <p class="character-count" :class="{ 'over-limit': rejectionAlternative.length > REJECTION_LIMIT }">
          {{ rejectionAlternative.length }}/{{ REJECTION_LIMIT }} characters
        </p>
        <p v-if="rejectionOverLimit" class="field-error" role="alert">
          Each field has a maximum of {{ REJECTION_LIMIT }} characters. Shorten the text to continue.
        </p>
        <p v-if="rejectionError" class="field-error" role="alert">{{ rejectionError }}</p>
        <div class="confirmation-actions">
          <button type="button" class="btn-primary secondary" :disabled="rejectingId !== null"
            @click="cancelRejection">Cancel</button>
          <button type="button" class="btn-danger reject-btn"
            :disabled="rejectingId !== null || rejectionOverLimit"
            @click="confirmRejection">
            {{ rejectingId !== null ? "Rejecting..." : "Yes, Reject" }}
          </button>
        </div>
      </div>
    </div>

    <!-- Approval confirmation pop-up -->
    <div
      v-if="bookingToApprove"
      class="modal-backdrop"
      @click.self="cancelApproval"
    >
      <div
        class="confirmation-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="approve-dialog-title"
        aria-describedby="approve-dialog-description"
      >
        <h3 id="approve-dialog-title">
          Approve booking request?
        </h3>

        <p id="approve-dialog-description">
          Are you sure you want to approve the booking for
          <strong>
            {{ bookingToApprove.eventName || `Event #${bookingToApprove.eventId}` }}
          </strong>
          at
          <strong>
            {{ bookingToApprove.venueName || `Venue #${bookingToApprove.venueId}` }}
          </strong>?

          This will confirm the venue for the event.
        </p>

        <p class="dialog-time">
          <strong>Start:</strong>
          {{ formatDate(bookingToApprove.startDatetime) }}
          {{ formatTime(bookingToApprove.startDatetime) }}

          <br />

          <strong>End:</strong>
          {{ formatDate(bookingToApprove.endDatetime) }}
          {{ formatTime(bookingToApprove.endDatetime) }}
        </p>

        <div class="confirmation-actions">
          <button
            type="button"
            class="btn-primary secondary"
            :disabled="approvingId !== null || rejectingId !== null"
            @click="cancelApproval"
          >
            Cancel
          </button>

          <button
            type="button"
            class="btn-primary"
            :disabled="approvingId !== null || rejectingId !== null"
            @click="confirmApproval"
          >
            {{ approvingId !== null ? "Approving..." : "Yes, Approve" }}
          </button>
        </div>
      </div>
    </div>
    <!-- Release Hold Confirmation -->
    <div v-if="holdToRelease" class="modal-backdrop" @click.self="closeReleaseConfirmation">
      <div class="confirmation-dialog" role="alertdialog" aria-modal="true"
        aria-labelledby="release-dialog-title" aria-describedby="release-dialog-description">
        <h3 id="release-dialog-title">Release tentative hold?</h3>
        <p id="release-dialog-description">
          Are you sure you want to release the tentative hold for
          <strong>{{ holdToRelease.eventName || `Event #${holdToRelease.eventId}` }}</strong>
          at <strong>{{ holdToRelease.venueName || `Venue #${holdToRelease.venueId}` }}</strong>?
          The venue will become available for other booking requests.
        </p>
        <p class="dialog-time">
          <strong>Current hold expiry:</strong> {{ formatHoldExpiry(holdToRelease.holdExpiresAt) }}
        </p>
        <p v-if="releaseError" class="field-error" role="alert">{{ releaseError }}</p>
        <div class="confirmation-actions">
          <button type="button" class="btn-primary secondary" :disabled="releasingId !== null"
            @click="closeReleaseConfirmation">Keep Hold</button>
          <button type="button" class="btn-danger reject-btn" :disabled="releasingId !== null"
            @click="releaseHold">{{ releasingId !== null ? 'Releasing...' : 'Yes, Release Hold' }}</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import venuesApi from "../api/venues";
import apiClient from "../api/client";

const bookings = ref([]);
const holdBooking = ref(null);
const holdAction = ref('place');
const holdExpiry = ref('');
const holdError = ref('');
const holdSaving = ref(false);
function parseUtcHoldExpiry(value) {
  const text = String(value);
  return new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(text) ? text : `${text}Z`);
}
function formatHoldExpiry(value) {
  if (!value) return 'Not specified';
  return parseUtcHoldExpiry(value).toLocaleString('en-SG', {
    timeZone: 'Asia/Singapore', day: '2-digit', month: '2-digit', year: 'numeric',
    hour: 'numeric', minute: '2-digit', hour12: true
  });
}
function openHold(booking, action) {
  holdBooking.value = booking;
  holdAction.value = action;
  holdExpiry.value = action === 'extend' && booking.holdExpiresAt
    ? parseUtcHoldExpiry(booking.holdExpiresAt).toLocaleString('sv-SE').replace(' ', 'T').slice(0, 16)
    : '';
  holdError.value = '';
}
async function saveHold() {
  if (!holdBooking.value || holdSaving.value) return;
  const expiry = new Date(holdExpiry.value);
  if (!holdExpiry.value || Number.isNaN(expiry.getTime()) || expiry <= new Date()) {
    holdError.value = 'Enter a future expiry date and time.';
    return;
  }
  holdSaving.value = true;
  try {
    const path = holdAction.value === 'extend' ? '/hold/extend' : '/hold';
    await apiClient.post(`/venues/bookings/${holdBooking.value.id}${path}`, { expiresAt: expiry.toISOString() });
    holdBooking.value = null;
    await loadPendingBookings();
    notice.value = 'Tentative hold saved successfully.';
  } catch (err) {
    holdError.value = err.response?.data?.error || 'Could not save the hold.';
  } finally {
    holdSaving.value = false;
  }
}
const holdToRelease = ref(null);
const releasingId = ref(null);
const releaseError = ref('');
function openReleaseConfirmation(booking) {
  holdToRelease.value = booking;
  releaseError.value = '';
}
function closeReleaseConfirmation() {
  if (releasingId.value !== null) return;
  holdToRelease.value = null;
  releaseError.value = '';
}
async function releaseHold() {
  const booking = holdToRelease.value;
  if (!booking || releasingId.value !== null) return;
  releasingId.value = booking.id;
  releaseError.value = '';
  try {
    await apiClient.post(`/venues/bookings/${booking.id}/hold/release`);
    holdToRelease.value = null;
    await loadPendingBookings();
    notice.value = 'Tentative hold released successfully.';
  } catch (err) {
    releaseError.value = err.response?.data?.error || 'Could not release the hold.';
  } finally {
    releasingId.value = null;
  }
}

const approvedBookings = ref([]);
const activeTab = ref("pending");
const displayedBookings = computed(() => activeTab.value === "pending" ? bookings.value : approvedBookings.value);
const bookingToCancel = ref(null);
const cancellingId = ref(null);
const cancellationReason = ref("");
const cancellationError = ref("");
const loading = ref(false);
const error = ref("");
const notice = ref("");
const approvingId = ref(null);
const bookingToApprove = ref(null);
const REJECTION_LIMIT = 500;
const bookingToReject = ref(null);
const rejectingId = ref(null);
const rejectionReason = ref("");
const rejectionAlternative = ref("");
const rejectionError = ref("");
const rejectionOverLimit = computed(() =>
  rejectionReason.value.length > REJECTION_LIMIT ||
  rejectionAlternative.value.length > REJECTION_LIMIT
);


function formatDate(value) {
  if (!value) return "Not specified";

  const [year, month, day] = String(value)
    .slice(0, 10)
    .split("-");

  return year && month && day
    ? `${day}/${month}/${year}`
    : "Not specified";
}

function formatTime(value) {
  if (!value) return "Not specified";

  return (
    String(value)
      .replace(" ", "T")
      .split("T")[1]
      ?.slice(0, 5) || "Not specified"
  );
}

async function loadPendingBookings() {
  loading.value = true;
  error.value = "";
  bookings.value = [];

  try {
    const { data } = await venuesApi.getPendingBookings();

    if (!Array.isArray(data)) {
      throw new Error("Unexpected response format");
    }

    bookings.value = data
      .filter((booking) => booking.status === "pending" || booking.status === "held")
      .sort((a, b) =>
        String(a.startDatetime || "").localeCompare(
          String(b.startDatetime || "")
        )
      );
  } catch (err) {
    error.value =
      err.response?.data?.error ||
      "Could not load pending booking requests.";
  } finally {
    loading.value = false;
  }
}

async function loadApprovedBookings() {
  loading.value = true;
  error.value = "";
  approvedBookings.value = [];
  try {
    const { data } = await venuesApi.getApprovedBookings();
    if (!Array.isArray(data)) throw new Error("Unexpected response format");
    approvedBookings.value = data.filter((b) => b.status === "approved")
      .sort((a, b) => String(a.startDatetime || "").localeCompare(String(b.startDatetime || "")));
  } catch (err) {
    error.value = err.response?.data?.error || "Could not load approved bookings.";
  } finally {
    loading.value = false;
  }
}

function refreshBookings() {
  return activeTab.value === "pending" ? loadPendingBookings() : loadApprovedBookings();
}

function switchBookingTab(tab) {
  if (cancellingId.value !== null || approvingId.value !== null || rejectingId.value !== null) return;
  activeTab.value = tab;
  notice.value = "";
  error.value = "";
  refreshBookings();
}

function openCancellationConfirmation(booking) {
  if (booking.status !== "approved" || cancellingId.value !== null) return;
  bookingToCancel.value = booking;
  cancellationReason.value = "";
  cancellationError.value = "";
  notice.value = "";
}

function closeCancellation() {
  if (cancellingId.value !== null) return;
  bookingToCancel.value = null;
  cancellationError.value = "";
}

async function confirmCancellation() {
  const current = bookingToCancel.value;
  if (!current || cancellingId.value !== null || cancellationReason.value.length > REJECTION_LIMIT) return;
  cancellingId.value = current.id;
  cancellationError.value = "";
  error.value = "";
  notice.value = "";
  try {
    await venuesApi.cancelBooking(current.id, { reason: cancellationReason.value.trim() });
    bookingToCancel.value = null;
    await loadApprovedBookings();
    notice.value = "Booking cancelled successfully. The Event Coordinator can view its updated status.";
  } catch (err) {
    const message = err.response?.data?.error || "Unable to cancel this booking.";
    if ([400, 403, 409].includes(err.response?.status)) {
      bookingToCancel.value = null;
      await loadApprovedBookings();
      error.value = message;
    } else {
      cancellationError.value = message;
    }
  } finally {
    cancellingId.value = null;
  }
}

function openApprovalConfirmation(booking) {
  if (
    approvingId.value !== null ||
    !["pending", "held"].includes(booking.status)
  ) {
    return;
  }

  bookingToApprove.value = booking;
  error.value = "";
}

function cancelApproval() {
  if (approvingId.value !== null) return;

  bookingToApprove.value = null;
}

async function confirmApproval() {
  const booking = bookingToApprove.value;

  if (!booking || approvingId.value !== null) return;

  approvingId.value = booking.id;
  error.value = "";
  notice.value = "";

  try {
    await venuesApi.approveBooking(booking.id);

    bookingToApprove.value = null;

    await loadPendingBookings();

    notice.value =
      "Booking approved successfully. The venue is confirmed for the event.";
  } catch (err) {
    bookingToApprove.value = null;

    const message =
      err.response?.data?.error ||
      "Unable to approve this booking.";

    if (err.response?.status === 409) {
      await loadPendingBookings();
    }

    error.value = message;
  } finally {
    approvingId.value = null;
  }
}

function openRejectionConfirmation(booking) {
  if (approvingId.value !== null || rejectingId.value !== null || booking.status !== "pending") return;
  bookingToReject.value = booking;
  rejectionReason.value = "";
  rejectionAlternative.value = "";
  rejectionError.value = "";
  error.value = "";
  notice.value = "";
}

function cancelRejection() {
  if (rejectingId.value !== null) return;
  bookingToReject.value = null;
  rejectionError.value = "";
}

async function confirmRejection() {
  const current = bookingToReject.value;
  if (!current || rejectingId.value !== null || rejectionOverLimit.value) return;
  rejectingId.value = current.id;
  rejectionError.value = "";
  error.value = "";
  notice.value = "";
  try {
    await venuesApi.rejectBooking(current.id, {
      reason: rejectionReason.value.trim(),
      alternativeSuggestion: rejectionAlternative.value.trim(),
    });
    bookingToReject.value = null;
    await loadPendingBookings();
    notice.value = "Booking rejected successfully. The Coordinator can view the decision and any feedback.";
  } catch (err) {
    const message = err.response?.data?.error || "Unable to reject this booking.";
    if (err.response?.status === 409) {
      bookingToReject.value = null;
      await loadPendingBookings();
      error.value = message;
    } else {
      rejectionError.value = message;
    }
  } finally {
    rejectingId.value = null;
  }
}

onMounted(loadPendingBookings);
</script>

<style scoped>
.hold-info { color: #7b5c13; font-weight: 600; margin: .75rem 0; }

.booking-tabs { display: flex; gap: .5rem; margin-bottom: 1.25rem; border-bottom: 1px solid var(--border, #e4defa); }
.booking-tab { padding: .8rem 1rem; border: none; border-bottom: 3px solid transparent; background: transparent; color: var(--text-muted, #6b6890); font: inherit; font-weight: 600; cursor: pointer; }
.booking-tab.active { color: var(--lilac-text, #4b3fa0); border-bottom-color: var(--primary, #6d5bd0); }

.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.page-title {
  margin: 0;
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.intro {
  margin: 0 0 1rem;
  color: var(--text-muted, #6b6890);
}

.card {
  padding: 1.25rem 1.5rem;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e4defa);
  border-radius: 14px;
  box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08);
}

.summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.summary-label {
  font-weight: 600;
  color: var(--text, #2d2a4a);
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 1rem;
}

.booking header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.5rem;
}

.booking h3 {
  margin: 0 0 0.4rem;
  font-size: 1.1rem;
  color: var(--text, #2d2a4a);
}

.meta {
  margin: 0.2rem 0;
  color: var(--text-muted, #6b6890);
  font-size: 0.92rem;
}

.meta strong {
  color: var(--text, #2d2a4a);
  font-weight: 600;
}

.desc {
  color: var(--text, #2d2a4a);
  margin: 0.75rem 0 0;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border, #e4defa);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-top: 0.7rem;
}

.badge {
  padding: 0.15rem 0.6rem;
  border-radius: 999px;
  font-size: 0.82rem;
  font-weight: 500;
  white-space: nowrap;
}

.cap {
  background: var(--butter-bg, #fef3c7);
  color: var(--butter-text, #92400e);
}

.sky {
  background: var(--sky-bg, #e3f2ff);
  color: var(--sky-text, #356b99);
}

.lilac {
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
}

.btn-primary {
  padding: 0.5rem 1.2rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-weight: 500;
  background: var(--primary, #6d5bd0);
  color: #fff;
  cursor: pointer;
}

.btn-primary:hover {
  background: var(--primary-hover, #5b49bd);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary:focus-visible {
  outline: 2px solid var(--primary, #6d5bd0);
  outline-offset: 2px;
}

.approve-btn {
  margin-top: 1rem;
}

.success {
  color: #166534;
  background: #dcfce7;
  padding: 0.7rem 1rem;
  border-radius: 10px;
}

.field-error {
  color: #a12b47;
  font-size: 0.875rem;
}

.empty {
  padding: 1rem;
  color: var(--text-muted, #6b6890);
}

/* Confirmation modal - same style as Withdraw Booking */
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(28, 22, 54, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.confirmation-dialog {
  width: min(100%, 430px);
  padding: 1.5rem;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 16px 45px rgba(0, 0, 0, 0.2);
}

.confirmation-dialog h3 {
  margin: 0 0 0.75rem;
  color: var(--text, #2d2a4a);
}

.confirmation-dialog p {
  line-height: 1.5;
  color: var(--text, #2d2a4a);
}

.dialog-time {
  padding: 0.75rem;
  border-radius: 8px;
  background: #faf9ff;
}

.confirmation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.25rem;
}

.btn-primary.secondary {
  background: var(--lilac-bg, #e9e5fb);
  color: var(--lilac-text, #4b3fa0);
}

.btn-primary.secondary:hover {
  background: #ddd6fb;
}

.booking-decision-actions { display: flex; flex-wrap: wrap; gap: .65rem; margin-top: 1rem; }
.booking-decision-actions .approve-btn { margin-top: 0; }
/* Match Venue Catalogue Edit / Deactivate buttons */
.btn-ghost, .btn-danger {
  padding: 0.5rem 1.2rem;
  border: none;
  border-radius: 999px;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}
.btn-ghost { background: var(--lilac-bg, #e9e5fb); color: var(--lilac-text, #4b3fa0); }
.btn-danger { background: var(--rose-bg, #fde8ee); color: var(--rose-text, #a12b47); }
.btn-ghost:disabled, .btn-danger:disabled { opacity: .6; cursor: not-allowed; }
.btn-ghost:focus-visible, .btn-danger:focus-visible { outline: 2px solid var(--primary, #6d5bd0); outline-offset: 2px; }
.rejection-dialog { max-height: calc(100vh - 2rem); overflow-y: auto; }
.rejection-label { display: block; margin: .8rem 0 .35rem; font-weight: 600; color: var(--text, #2d2a4a); }
.rejection-dialog textarea { box-sizing: border-box; width: 100%; padding: .7rem; border: 1px solid var(--border, #e4defa); border-radius: 8px; font: inherit; resize: vertical; }
.character-count { margin: .25rem 0 .5rem; font-size: .8rem; color: var(--text-muted, #6b6890); text-align: right; }
.character-count.over-limit { color: #a12b47; font-weight: 600; }

@media (max-width: 560px) {
  .head {
    flex-wrap: wrap;
  }

  .summary {
    flex-wrap: wrap;
  }
}
</style>


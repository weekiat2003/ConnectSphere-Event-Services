<template>
    <div class="card panel">
      <h3 class="section-title">Venue Requirements</h3>
  
      <p v-if="requirements" class="required-summary">
        <span><strong>Capacity needed:</strong> {{ requirements.capacityNeeded ?? "—" }}</span>
        <span><strong>Layout:</strong> {{ requirements.requiredLayout || "—" }}</span>
        <span v-if="requirements.requiredFacilities?.length">
          <strong>Facilities:</strong> {{ requirements.requiredFacilities.join(", ") }}
        </span>
      </p>
  
      <p v-if="!currentBookings.length" class="empty">No venue booked yet.</p>
      <table v-else class="req-table">
        <thead>
          <tr>
            <th>Venue</th><th>Location</th><th>Capacity</th><th>Booking period</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="b in currentBookings" :key="b.id">
            <td>{{ b.venueName || `Venue #${b.venueId}` }}</td>
            <td>{{ b.venueLocation || "—" }}</td>
            <td>{{ b.venueCapacity ?? "—" }}</td>
            <td>{{ formatPeriod(b.startDatetime, b.endDatetime) }}</td>
            <td>
              <StatusBadge kind="venue" :status="b.status" />
              <span v-if="b.status === 'held' && b.holdExpiresAt" class="hold-note">
                until {{ formatHoldExpiry(b.holdExpiresAt) }}
              </span>
              <span v-if="b.needsReconsideration" class="badge-warn">Needs reconsideration</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
  
  <script setup>
  import { computed } from "vue";
  import StatusBadge from "./StatusBadge.vue";
  
  const props = defineProps({
    bookings: { type: Array, default: () => [] },
    requirements: { type: Object, default: null },
  });
  
  // Rejected, withdrawn, cancelled, expired and released bookings are history, not the current venue.
  const CURRENT = ["pending", "held", "approved"];
  const currentBookings = computed(() =>
    props.bookings
      .filter((b) => CURRENT.includes(b.status))
      .sort((a, b) => String(a.startDatetime).localeCompare(String(b.startDatetime)))
  );
  
  // Booking times are naive wall-clock values, so show them as stored.
  const wall = (v) => String(v || "").replace("T", " ").slice(0, 16);
  function formatPeriod(start, end) {
    if (!start) return "—";
    const s = wall(start), e = wall(end);
    return s.slice(0, 10) === e.slice(0, 10) ? `${s} – ${e.slice(11)}` : `${s} – ${e}`;
  }
  
  // Hold expiry is stored in UTC.
  function formatHoldExpiry(value) {
    const text = String(value).trim().replace(" ", "T");
    const d = new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`);
    return Number.isNaN(d.getTime())
      ? ""
      : d.toLocaleString("en-SG", {
          timeZone: "Asia/Singapore", day: "2-digit", month: "2-digit", year: "numeric",
          hour: "numeric", minute: "2-digit", hour12: true,
        });
  }
  </script>
  
  <style scoped>
  .card { background: var(--surface, #fff); border: 1px solid var(--border, #e4defa); border-radius: 14px;
    box-shadow: 0 4px 16px rgba(109, 91, 208, 0.08); padding: 1rem; margin-bottom: 1rem; overflow-x: auto; }
  .section-title { margin: 0 0 0.75rem; font-size: 1.1rem; font-weight: 600; }
  .required-summary { display: flex; flex-wrap: wrap; gap: 0.4rem 1.5rem; margin: 0 0 0.75rem;
    font-size: 0.9rem; color: var(--text-muted, #6b6890); }
  .req-table { width: 100%; border-collapse: collapse; }
  .req-table th, .req-table td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid var(--border, #e4defa); vertical-align: top; }
  .req-table th { font-size: 0.8rem; color: var(--text-muted, #6b6890); font-weight: 500; white-space: nowrap; }
  .hold-note { display: block; font-size: 0.75rem; color: var(--text-muted, #6b6890); }
  .badge-warn { display: inline-block; margin-top: 0.2rem; padding: 0.15rem 0.65rem; border-radius: 999px; font-size: 0.8rem; font-weight: 500;
    background: var(--butter-bg, #fff1c2); color: var(--butter-text, #8a5a00); }
  .empty { color: var(--text-muted, #6b6890); margin: 0; }
  </style>
<template>
  <div id="layout">
    <nav v-if="auth.isAuthenticated">
      <div class="nav-inner">
        <router-link to="/">Dashboard</router-link>
        <router-link v-if="auth.hasRole('event_organiser')" to="/events/new">New Request</router-link>
        <router-link v-if="auth.hasRole('event_organiser')" to="/drafts">My Drafts</router-link>
        <router-link v-if="auth.hasRole('event_coordinator')" to="/review">Review Queue</router-link>
        <router-link v-if="auth.hasRole('event_coordinator')" to="/change-requests">Change Requests</router-link>
        <router-link v-if="auth.hasRole('safety_officer')" to="/safety-reviews">Safety Reviews</router-link>
        <router-link v-if="auth.hasRole('event_coordinator') || auth.hasRole('safety_officer')" to="/planning">Planning View</router-link>
        <router-link v-if="auth.hasRole('event_coordinator')" to="/calendar">My Calendar</router-link>
        <router-link v-if="auth.hasRole('event_coordinator')" to="/venues/request">Venue Booking</router-link>
        <router-link v-if="auth.hasRole('venue_staff')" to="/venues/approval">Venue Approval</router-link>
        <router-link v-if="auth.hasRole('event_coordinator')" to="/venues/search">Venue Search</router-link>
        <router-link v-if="auth.hasRole('technical_support_staff')" to="/equipment">Equipment</router-link>
        <router-link v-if="auth.hasRole('technical_support_staff')" to="/technical-review">Technical Review</router-link>
        <router-link v-if="auth.hasRole('venue_staff') || auth.hasRole('event_coordinator')" to="/venues">Venue Catalogue</router-link>
        <router-link v-if="auth.hasRole('venue_staff') || auth.hasRole('event_coordinator')" to="/venues/availability">Venue Availability</router-link>
        <router-link v-if="auth.hasRole('attendee')" to="/attendee/events">Events</router-link>
        <router-link v-if="auth.hasRole('attendee')" to="/my-registrations">My Registrations</router-link>
        <router-link v-if="auth.hasRole('event_organiser') || auth.hasRole('event_coordinator')" to="/registrations/manage">Registrations</router-link>
        <span class="spacer" />
        <span class="user-name">{{ auth.user?.name }}</span>
        <button class="logout" @click="handleLogout">Logout</button>
      </div>

    </nav>
    <main>
      <router-view />
    </main>
    <ConfirmDialog />
  </div>
</template>

<script setup>
import { useRouter } from "vue-router";
import { useAuthStore } from "./stores/auth";
import ConfirmDialog from './components/ConfirmDialog.vue';

const auth = useAuthStore();
const router = useRouter();

async function handleLogout() {
  try {
    await auth.logout();
  } finally {
    router.replace({ name: "login" });
  }
}
</script>

<style>
/* Theme colours: change them here and the whole app follows */
:root {
  /* Main colours */
  --primary: #6d5bd0;
  --primary-hover: #5b49bd;
  --primary-tint: #ebe7ff;
  --bg: #f6f4ff;
  --surface: #ffffff;
  --border: #e4defa;
  --text: #2d2a4a;
  --text-muted: #6b6890;

  /* Pastel pairs: soft background + darker text so it stays readable */
  --lilac-bg: #e9e5fb;
  --lilac-text: #4b3fa0;
  --mint-bg: #d3f5e3;
  --mint-text: #1e6b47;
  --butter-bg: #fff1c2;
  --butter-text: #8a5a00;
  --rose-bg: #ffdce3;
  --rose-text: #a12b47;
  --sky-bg: #d6ecff;
  --sky-text: #1f5f99;
}

body {
  margin: 0;
  color: var(--text);
  background-color: var(--bg);
  /* soft lavender wash at the top of every page */
  background-image: linear-gradient(180deg, #ece7ff 0%, var(--bg) 300px);
  background-repeat: no-repeat;
}

#layout {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  min-height: 100vh;
}

/* Top bar spans the full width, content inside stays centred */
nav {
  background: rgba(255, 255, 255, 0.8);
  border-bottom: 1px solid var(--border);
}

.nav-inner {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
  max-width: 960px;
  margin: 0 auto;
  padding: 0.6rem 1rem;
}

nav a {
  padding: 0.4rem 0.85rem;
  border-radius: 999px;
  text-decoration: none;
  color: var(--text-muted);
  font-weight: 500;
}

nav a:hover {
  background: var(--lilac-bg);
  color: var(--lilac-text);
}

/* Current page */
nav a.router-link-exact-active {
  background: var(--primary-tint);
  color: var(--primary);
}

nav a:focus-visible,
.logout:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
}

.spacer {
  flex: 1;
}

.user-name {
  margin-right: 0.5rem;
  color: var(--text-muted);
  font-size: 0.9rem;
}

.logout {
  padding: 0.4rem 0.95rem;
  border: none;
  border-radius: 999px;
  background: var(--rose-bg);
  color: var(--rose-text);
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.logout:hover {
  background: #ffc9d4;
}

/* Page content area */
main {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem 1rem;
}

/* Base table look for any view that doesn't style its own */
table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  text-align: left;
  padding: 0.5rem;
  border-bottom: 1px solid var(--border);
}

button {
  cursor: pointer;
}
</style>
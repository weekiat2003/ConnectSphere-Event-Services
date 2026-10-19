import {
  createRouter,
  createWebHistory,
} from "vue-router";

import { useAuthStore } from "../stores/auth";

import LoginView from "../views/LoginView.vue";
import DashboardView from "../views/DashboardView.vue";
import DraftsView from "../views/DraftsView.vue";
import EventCreateView from "../views/EventCreateView.vue";
import ReviewQueueView from "../views/ReviewQueueView.vue";
import EventDetailView from "../views/EventDetailView.vue";
import PlanningView from "../views/PlanningView.vue";
import CoordinatorCalendar from "../components/CoordinatorCalendar.vue";
import VenueBookingRequestView from "../views/VenueBookingRequestView.vue";
import VenueSearchView from "../views/VenueSearchView.vue";
import EquipmentView from "../views/EquipmentView.vue";

import VenueCatalogueView from "../views/VenueCatalogueView.vue";
import VenueAvailabilityView from "../views/VenueAvailabilityView.vue";
import VenueBookingApprovalView from "../views/VenueBookingApprovalView.vue";
import ChangeRequestReviewView from "../views/ChangeRequestReviewView.vue";
import SafetyReviewListView from "../views/SafetyReviewListView.vue";
import SafetyAssessmentView from "../views/SafetyAssessmentView.vue";
import AccessDeniedView from "../views/AccessDeniedView.vue";

import AttendeeEventsView from "../views/AttendeeEventsView.vue";
import AttendeeEventDetailView from "../views/AttendeeEventDetailView.vue";
import MyRegistrationsView from "../views/MyRegistrationsView.vue";
import RegistrationManageView from "../views/RegistrationManageView.vue";

const routes = [
  {
    path: "/login",
    name: "login",
    component: LoginView,
  },

  {
    path: "/",
    name: "dashboard",
    component: DashboardView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/drafts",
    name: "drafts",
    component: DraftsView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/events/new",
    name: "event-create",
    component: EventCreateView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/events/drafts/:id/edit",
    name: "edit-draft",
    component: EventCreateView,
    meta: {
      requiresAuth: true,
      roles: ["event_organiser"],
    },
  },

  {
    path: "/review",
    name: "review-queue",
    component: ReviewQueueView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/events/:id",
    name: "event-detail",
    component: EventDetailView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/planning",
    name: "planning",
    component: PlanningView,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/calendar",
    name: "calendar",
    component: CoordinatorCalendar,
    meta: {
      requiresAuth: true,
    },
  },

  {
    path: "/venues/search",
    name: "venue-search",
    component: VenueSearchView,
    meta: { requiresAuth: true, roles: ["event_coordinator"] },
  },

  {
    path: "/venues/request",
    name: "venue-booking-request",
    component: VenueBookingRequestView,
    meta: {
      requiresAuth: true,
      roles: ["event_coordinator"],
    },
  },

  {
    path: "/equipment",
    name: "equipment",
    component: EquipmentView,
    meta: {
      requiresAuth: true,
      roles: ["technical_support_staff"],
    },
  },
  
  {
    path: "/venues/availability",
    name: "venue-availability",
    component: VenueAvailabilityView,
    meta: { requiresAuth: true, roles: ["venue_staff", "event_coordinator"] },
  },

  {
    path: "/venues",
    name: "venue-catalogue",
    component: VenueCatalogueView,
    meta: { requiresAuth: true, roles: ["venue_staff", "event_coordinator"] },
  },

  {
  path: "/venues/approval",
  name: "venue-booking-approval",
  component: VenueBookingApprovalView,
  meta: {
    requiresAuth: true,
    roles: ["venue_staff"],
  },
  },
  // Operational Safety Check. showAccessDenied: other roles are told they
  // are not allowed, instead of being silently sent to the Dashboard.
  {
    path: "/safety-reviews",
    name: "safety-reviews",
    component: SafetyReviewListView,
    meta: { requiresAuth: true, roles: ["safety_officer"], showAccessDenied: true },
  },
  {
    path: "/safety-reviews/:id",
    name: "safety-assessment",
    component: SafetyAssessmentView,
    meta: { requiresAuth: true, roles: ["safety_officer"], showAccessDenied: true },
  },
  {
    path: "/access-denied",
    name: "access-denied",
    component: AccessDeniedView,
    meta: { requiresAuth: true },
  },
  { path: "/change-requests", 
    name: "change-request-review", 
    component: ChangeRequestReviewView, 
    meta: { 
      requiresAuth: true }
  },
  { path: "/attendee/events", 
    name: "attendee-events", 
    component: AttendeeEventsView, 
    meta: { 
      requiresAuth: true, 
      roles: ["attendee"] } 
  },
  { path: "/attendee/events/:id", 
    name: "attendee-event-detail", 
    component: AttendeeEventDetailView, 
    meta: { 
      requiresAuth: true, 
      roles: ["attendee"] } 
  },
  { path: "/my-registrations", 
    name: "my-registrations", 
    component: MyRegistrationsView, 
    meta: { 
      requiresAuth: true, 
      roles: ["attendee"] } 
  },
  { path: "/registrations/manage", 
    name: "registration-manage", 
    component: RegistrationManageView, 
    meta: { 
      requiresAuth: true, 
      roles: ["event_organiser", "event_coordinator"] } 
  },
];


const router = createRouter({
  history: createWebHistory(),
  routes,
});


router.beforeEach((to) => {
  const auth = useAuthStore();

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: "login" };
  }

  if (
    to.name === "dashboard" &&
    auth.hasRole("venue_staff") &&
    !auth.hasRole("event_organiser") &&
    !auth.hasRole("event_coordinator")
  ) {
    return { name: "venue-booking-approval" };
  }

  if (to.meta.roles && !to.meta.roles.some((role) => auth.hasRole(role))) {
    // Safety pages tell other roles they are not allowed, instead of
    // silently sending them to the Dashboard.
    if (to.meta.showAccessDenied) {
      return { name: "access-denied", query: { roles: to.meta.roles } };
    }
    return { name: "dashboard" };
  }
});

export default router;
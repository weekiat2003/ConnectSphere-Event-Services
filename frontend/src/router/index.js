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
  { path: "/change-requests", 
    name: "change-request-review", 
    component: ChangeRequestReviewView, 
    meta: { 
      requiresAuth: true }
  },
];


const router = createRouter({
  history: createWebHistory(),
  routes,
});


router.beforeEach((to) => {
  const auth = useAuthStore();

  if (
    to.meta.requiresAuth &&
    !auth.isAuthenticated
  ) {
    return {
      name: "login",
    };
  }

  if (
    to.meta.roles &&
    !to.meta.roles.some(
      (role) => auth.hasRole(role)
    )
  ) {
    return {
      name: "dashboard",
    };
  }
});


export default router;
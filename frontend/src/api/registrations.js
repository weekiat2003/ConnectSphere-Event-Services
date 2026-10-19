import apiClient from "./client";

export default {
  // Attendees
  listEvents: () => apiClient.get("/registrations/events"),
  getEvent: (id) => apiClient.get(`/registrations/events/${id}`),
  register: (id) => apiClient.post(`/registrations/events/${id}/register`),
  joinWaitlist: (id) => apiClient.post(`/registrations/events/${id}/waitlist`),
  withdraw: (registrationId) => apiClient.post(`/registrations/${registrationId}/withdraw`),
  mine: () => apiClient.get("/registrations/mine"),

  // Organisers and coordinators
  managedEvents: () => apiClient.get("/registrations/manage/events"),
  openRegistration: (id) => apiClient.post(`/registrations/events/${id}/open`),
  closeRegistration: (id) => apiClient.post(`/registrations/events/${id}/close`),
  attendees: (id, page = 1, pageSize = 50) =>
    apiClient.get(`/registrations/events/${id}/attendees`, { params: { page, pageSize } }),
};

import apiClient from "./client";

export default {
  list: ({ unread = false, limit = 50 } = {}) =>
    apiClient.get("/notifications", { params: { unread, limit } }),
  unreadCount: () => apiClient.get("/notifications/unread-count"),
  markRead: (id) => apiClient.post(`/notifications/${id}/read`),
  markAllRead: () => apiClient.post("/notifications/read-all"),
};

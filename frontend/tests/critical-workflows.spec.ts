import { expect, test, type Page, type Route } from "@playwright/test";

const admin = {
  id: 1,
  email: "admin@example.com",
  full_name: "Test Admin",
  role: "admin",
  is_active: true
};

async function mockApi(page: Page) {
  await page.route("http://localhost:8000/api/v1/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/login") {
      return route.fulfill({ json: { access_token: "test-token", token_type: "bearer", user: admin } });
    }
    if (path === "/auth/me") return route.fulfill({ json: admin });
    if (path === "/dashboard/summary") {
      return route.fulfill({ json: { total_vehicles: 1, status_summary: [{ status: 0, count: 1 }], location_summary: [{ location: "Belgrade", count: 1 }], reservation_status_summary: [] } });
    }
    if (path === "/notifications/unread-count") return route.fulfill({ json: { unread_count: 1 } });
    if (path === "/notifications") {
      return route.fulfill({ json: {
        items: [{
          id: 7, notification_type: "Work Order overdue", title: "Work Order #42 is overdue",
          message: "Brake repair", priority: "High", status: "Unread",
          entity_type: "WorkOrder", entity_id: 42, created_at: new Date().toISOString()
        }],
        page: 1, page_size: 20, total: 1, pages: 1
      } });
    }
    if (path === "/notifications/7/read") {
      return route.fulfill({ json: {
        id: 7, notification_type: "Work Order overdue", title: "Work Order #42 is overdue",
        message: "Brake repair", priority: "High", status: "Read",
        entity_type: "WorkOrder", entity_id: 42, created_at: new Date().toISOString(), read_at: new Date().toISOString()
      } });
    }
    if (path === "/notifications/read-all") return route.fulfill({ json: { message: "1 notification(s) marked as read." } });
    if (path === "/audit-logs") {
      return route.fulfill({ json: {
        items: [{
          id: 3, user_id: 1, username: "admin@example.com", action: "Vehicle created",
          entity_type: "Vehicle", entity_id: 9, description: "Vehicle 01-123-AB created.",
          old_values: null, new_values: { license_plate: "01-123-AB" }, created_at: new Date().toISOString()
        }],
        page: 1, page_size: 50, total: 1, pages: 1
      } });
    }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } });
  });
}

test("Admin can log in and view the notification centre", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");
  await page.getByLabel("Email").fill("admin@example.com");
  await page.getByLabel("Password").fill("password123");
  await page.getByRole("button", { name: "Login" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.getByRole("link", { name: "Notifications" }).click();
  await expect(page.getByRole("heading", { name: "Notifications" })).toBeVisible();
  await expect(page.getByText("Work Order #42 is overdue").first()).toBeVisible();
  await page.getByRole("button", { name: "Mark read" }).click();
});

test("Admin can filter and inspect redacted audit details", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("vehicle_fleet_control_token", "test-token"));
  await page.goto("/audit-logs");
  await expect(page.getByRole("heading", { name: "Audit Logs" })).toBeVisible();
  await expect(page.getByText("Vehicle created")).toBeVisible();
  await page.getByText("Inspect", { exact: true }).click();
  await expect(page.locator(".auditJson")).toContainText("01-123-AB");
  await expect(page.getByText(/hashed_password/)).toHaveCount(0);
});

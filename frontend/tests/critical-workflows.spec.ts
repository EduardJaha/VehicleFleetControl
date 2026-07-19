import { expect, test, type Page, type Route } from "@playwright/test";

const admin = {
  id: 1,
  email: "admin@example.com",
  full_name: "Test Admin",
  role: "admin",
  is_active: true
};

async function mockApi(page: Page) {
  const vehicles = [{
    id: 1, brand_id: 1, model_id: 1, brand: "Toyota", model: "Corolla",
    fuel_type: "Hybrid", vehicle_location: "Prishtina",
    registration_country: "AL", registration_country_name: "Albania",
    license_plate: "AA 123 AA", year: 2024, vin_number: null, engine_cc: 1800,
    odometer_km: 100, status: 0, status_name: "Active", archived: false
  }];
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
    if (path === "/vehicle-registration/countries") {
      return route.fulfill({ json: [
        {
          code: "AL", name: "Albania", placeholder: "AA 123 AA",
          example: "AA 123 AA", description: "Two letters, three digits, two letters",
          helper_text: ["Format: AA 123 AA", "Two letters, three digits, two letters"]
        },
        {
          code: "XK", name: "Kosovo", placeholder: "01-123-AB",
          example: "01-123-AB", description: "Region code, three digits, two letters",
          helper_text: ["Format: 01-123-AB", "Region codes: 01–07", "Number range: 101–999"]
        }
      ] });
    }
    if (path === "/vehicle-catalog/brands") {
      return route.fulfill({ json: [{ id: 1, name: "Toyota", is_active: true }] });
    }
    if (path === "/vehicle-catalog/brands/1/models") {
      return route.fulfill({ json: [{ id: 1, brand_id: 1, name: "Corolla", is_active: true }] });
    }
    if (path === "/vehicles" && route.request().method() === "GET") {
      return route.fulfill({ json: vehicles });
    }
    if (path === "/vehicles" && route.request().method() === "POST") {
      const request = route.request().postDataJSON();
      const created = {
        ...vehicles[0],
        ...request,
        id: 2,
        brand: "Toyota",
        model: "Corolla",
        registration_country_name: request.registration_country === "AL" ? "Albania" : "Kosovo"
      };
      vehicles.unshift(created);
      return route.fulfill({ status: 201, json: created });
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

test("Vehicle registration country controls formatting and creation", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("vehicle_fleet_control_token", "test-token"));
  await page.goto("/vehicles");
  await page.getByRole("button", { name: "Add Vehicle" }).click();

  const dialog = page.getByRole("dialog", { name: "Add Vehicle" });
  const country = dialog.getByLabel("Registration country");
  const plate = dialog.getByLabel("Licence plate");
  await expect(plate).toBeDisabled();
  await expect(plate).toHaveAttribute("placeholder", "Select a registration country first");

  await country.selectOption("AL");
  await expect(plate).toHaveAttribute("placeholder", "AA 123 AA");
  await plate.fill("aa123aa");
  await expect(plate).toHaveValue("AA 123 AA");

  await country.selectOption("XK");
  await expect(plate).toHaveValue("");
  await expect(plate).toHaveAttribute("placeholder", "01-123-AB");
  await plate.fill("01 123 ab");
  await expect(plate).toHaveValue("01-123-AB");

  await dialog.getByLabel("Brand").click();
  await dialog.getByRole("option", { name: "Toyota" }).click();
  await dialog.getByLabel("Model").click();
  await dialog.getByRole("option", { name: "Corolla" }).click();
  await dialog.getByLabel("Location").fill("Prishtina");
  await dialog.getByRole("button", { name: "Create Vehicle" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByText("01-123-AB", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("cell", { name: "Kosovo", exact: true }).first()).toBeVisible();
});

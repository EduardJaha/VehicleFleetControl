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
  }, {
    id: 2, brand_id: 2, model_id: 2, brand: "Tesla", model: "Model Y",
    fuel_type: "Electric", vehicle_location: "Tirana",
    registration_country: "XK", registration_country_name: "Kosovo",
    license_plate: "01-555-AA", year: 2025, vin_number: null, engine_cc: null,
    odometer_km: 21850, status: 0, status_name: "Active", archived: false
  }];
  const fuelRecords: Array<Record<string, unknown>> = [];
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
    if (path === "/fuel/all" && route.request().method() === "GET") {
      return route.fulfill({ json: fuelRecords });
    }
    if (path === "/fuel" && route.request().method() === "POST") {
      fuelRecords.unshift({
        id: 10,
        vehicle_id: 2,
        license_plate: "01-555-AA",
        brand: "Tesla",
        model: "Model Y",
        refuel_date: "19-07-2026",
        fuel_type: "Electric",
        quantity: 62.4,
        unit: "KWH",
        unit_cost: 0.18,
        total_cost: 11.23,
        location: "Tirana",
        station_name: "Public Charger",
        bill_file_path: null,
        odometer_km: 21850,
        archived: false,
        unit_review_required: false
      });
      return route.fulfill({ json: { message: "Fuel or charging record added for 01-555-AA." } });
    }
    if (path === "/fuel/10" && route.request().method() === "PUT") {
      return route.fulfill({ json: { message: "Fuel or charging record updated successfully." } });
    }
    return route.fulfill({ status: 404, json: { detail: `Unmocked ${path}` } });
  });
}

test("Language selector updates the login UI, HTML language, and persisted preference", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Language").selectOption("sq");
  await expect(page.getByLabel("Gjuha")).toHaveValue("sq");
  await expect(page.getByLabel("Email-i")).toBeVisible();
  await expect(page.getByRole("button", { name: "Hyr" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "sq");
  await page.reload();
  await expect(page.getByLabel("Gjuha")).toHaveValue("sq");
  await expect(page.locator("html")).toHaveAttribute("lang", "sq");
});

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
  await expect(page.getByText("Vehicle created").first()).toBeVisible();
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

test("Fuel form derives Electric units from the selected Vehicle and resets safely", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("vehicle_fleet_control_token", "test-token"));
  await page.goto("/fuel");
  await page.getByRole("button", { name: "Add Fuel Record" }).click();

  const dialog = page.getByRole("dialog", { name: "Add Fuel Record" });
  const quantity = dialog.getByLabel("Quantity");
  const unitCost = dialog.getByLabel("Unit cost");
  await expect(quantity).toBeDisabled();
  await expect(unitCost).toBeDisabled();
  await expect(dialog.getByText("Select a Vehicle first").first()).toBeVisible();

  await dialog.getByLabel("Vehicle").click();
  await dialog.getByRole("option", { name: "01-555-AA — Tesla Model Y — Electric" }).click();
  await expect(dialog.getByLabel("Energy type")).toHaveText("Electric");
  await expect(dialog.getByLabel("Energy delivered (kWh)")).toBeEnabled();
  await expect(dialog.getByLabel("Cost per kWh")).toBeEnabled();
  await dialog.getByLabel("Energy delivered (kWh)").fill("62.4");
  await dialog.getByLabel("Cost per kWh").fill("0.18");
  await expect(dialog.getByLabel("Calculated total")).toHaveValue("11.23");

  await dialog.getByLabel("Vehicle").click();
  await dialog.getByRole("option", { name: "AA 123 AA — Toyota Corolla — Hybrid" }).click();
  await expect(dialog.getByLabel("Fuel quantity (L)")).toHaveValue("");
  await expect(dialog.getByLabel("Cost per litre")).toHaveValue("");

  await dialog.getByLabel("Vehicle").click();
  await dialog.getByRole("option", { name: "01-555-AA — Tesla Model Y — Electric" }).click();
  await dialog.getByLabel("Energy delivered (kWh)").fill("62.4");
  await dialog.getByLabel("Cost per kWh").fill("0.18");
  await dialog.getByLabel("Charging station / provider").fill("Public Charger");
  await dialog.getByRole("button", { name: "Save Fuel Record" }).click();

  await expect(dialog).toBeHidden();
  await expect(page.getByRole("cell", { name: "62.4 kWh" })).toBeVisible();
  await expect(page.getByRole("cell", { name: "0.18/kWh" })).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByLabel("Energy delivered (kWh)")).toBeVisible();
  await expect(page.getByLabel("Cost per kWh")).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "01-555-AA" }).locator("select")).toHaveCount(0);
});

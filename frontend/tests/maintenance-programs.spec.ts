import { expect, test, type Page } from "@playwright/test";

async function programApi(page: Page, role = "admin") {
  const programs: Array<Record<string, unknown>> = [];
  const rules: Array<Record<string, unknown>> = [];
  const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
  await page.addInitScript(() => {
    localStorage.setItem("vehicle_fleet_control_token", "program-test");
    localStorage.setItem("vehicleFleetControl.language", "en");
  });
  await page.route("http://localhost:8000/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    const body = method !== "GET" && method !== "DELETE" ? request.postDataJSON() as Record<string, unknown> : {};
    if (method !== "GET") requests.push({ path, body });
    if (path === "/auth/me") return route.fulfill({ json: { id: 1, email: "admin@test.local", full_name: "Program Admin", role, is_active: true, preferred_language: "en" } });
    if (path === "/auth/me/language") return route.fulfill({ json: { preferred_language: body.language } });
    if (path === "/notifications/unread-count") return route.fulfill({ json: { unread_count: 0 } });
    if (path === "/maintenance/programs/options") return route.fulfill({ json: {
      vehicles: [{ id: 1, name: "01-111-AA · VW Golf" }], brands: ["VW"], models: [{ brand: "VW", model: "Golf" }],
      fuel_types: ["Diesel"], categories: ["Passenger"], locations: [{ id: 1, name: "Depot" }], departments: [{ id: 1, name: "Operations" }],
    } });
    if (path === "/maintenance/programs/compliance") {
      const assigned = rules.some(r => r.is_active !== false) && programs.some(p => !p.archived);
      return route.fulfill({ json: {
        vehicles_with_program: assigned ? 1 : 0, vehicles_without_program: assigned ? 0 : 1,
        tasks_current: 0, tasks_due_soon: 0, tasks_overdue: assigned ? 1 : 0, tasks_needing_baseline: 0,
        compliance_percent: assigned ? 0 : null, coverage_percent: assigned ? 100 : 0,
        vehicles: [{ vehicle_id: 1, license_plate: "01-111-AA", program_name: assigned ? programs[0].name : null, assignment: assigned ? { program_id: 1, rule_id: 1 } : null }],
        items: assigned ? [{ id: 1, vehicle_id: 1, title: "Engine Oil", service_type: "Oil Change", license_plate: "01-111-AA", status: "Overdue", due_date: "2026-01-01", due_odometer_km: 30000, work_order_id: null, whichever_occurs_first: true }] : [],
      } });
    }
    if (path === "/maintenance/programs/rules") {
      if (method === "POST") { const row = { ...body, id: rules.length + 1, is_active: true }; rules.push(row); return route.fulfill({ json: row }); }
      return route.fulfill({ json: rules });
    }
    if (path === "/maintenance/programs") {
      if (method === "POST") { const p = { ...body, id: programs.length + 1, archived: false, tasks: [] }; programs.push(p); return route.fulfill({ json: p }); }
      return route.fulfill({ json: programs });
    }
    if (path === "/maintenance/programs/1/tasks") {
      const row = { ...body, id: 1, program_id: 1 };
      (programs[0].tasks as unknown[]).push(row);
      return route.fulfill({ json: row });
    }
    if (path === "/maintenance/programs/1" && method === "DELETE") { programs[0].archived = true; return route.fulfill({ json: programs[0] }); }
    if (path === "/maintenance/programs/1/restore") { programs[0].archived = false; return route.fulfill({ json: programs[0] }); }
    return route.fulfill({ status: 404, json: { message: `Unmocked ${path}` } });
  });
  return { programs, rules, requests };
}

test("Programs UI creates tasks, assigns a real program, shows compliance and restores archives", async ({ page }) => {
  const state = await programApi(page);
  await page.goto("/maintenance/programs");
  await page.getByRole("button", { name: "Create Program", exact: true }).click();
  await page.getByLabel("Name", { exact: true }).fill("Diesel Passenger Program");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Diesel Passenger Program", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page.getByRole("button", { name: "Add Task", exact: true }).click();
  await page.getByLabel("Title", { exact: true }).fill("Engine Oil");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Engine Oil", exact: true })).toBeVisible();
  expect(state.requests.find(r => r.path.endsWith("/tasks"))?.body).toMatchObject({ km_interval: 10000, month_interval: 12, whichever_occurs_first: true, warning_km: 1000, warning_days: 30 });
  await page.getByRole("button", { name: "Assignments", exact: true }).click();
  await page.getByRole("button", { name: "Add Assignment Rule", exact: true }).click();
  await page.getByRole("combobox", { name: "Matching value", exact: true }).selectOption("1");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Governing assignments" })).toBeVisible();
  expect(state.rules[0]).toMatchObject({ program_id: 1, target_type: "Vehicle", target_value: "1" });
  await page.getByRole("button", { name: "Compliance", exact: true }).click();
  await expect(page.getByText("Tasks overdue", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Overdue", exact: true })).toBeVisible();
  await page.screenshot({ path: "/tmp/maintenance-programs-compliance.png", fullPage: true });
  await page.getByRole("button", { name: "Programs", exact: true }).click();
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await page.getByLabel("Include archived").check();
  await page.getByRole("button", { name: "Restore", exact: true }).click();
  await expect(page.getByRole("button", { name: "Archive", exact: true })).toBeVisible();
  await page.getByLabel("Language", { exact: true }).selectOption("sq");
  await expect(page.getByRole("heading", { name: "Programet e Mirëmbajtjes", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Krijo Program", exact: true })).toBeVisible();
});

test("Viewer can inspect programs without mutation controls", async ({ page }) => {
  await programApi(page, "viewer");
  await page.goto("/maintenance/programs");
  await expect(page.getByRole("heading", { name: "Maintenance Programs", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create Program", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Assignments", exact: true }).click();
  await expect(page.getByRole("button", { name: "Add Assignment Rule", exact: true })).toHaveCount(0);
});

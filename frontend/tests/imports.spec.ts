import { expect, test } from "@playwright/test";

const kinds = ["Historical Services", "Fuel and Charging Records", "Vehicle Assignments", "Documents Metadata", "Vendors", "Parts"];

for (const kind of kinds) {
  test(`${kind}: template, upload, map, validate, preview, explicit mode and confirm`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("vehicle_fleet_control_token", "test-token"));
    let current: Record<string, any> = {
      id: 1, entity_type: kind, filename: "source.csv", uploaded_by: 1, status: "Uploaded",
      source_headers: ["Identifier"], fields: [{ key: "name", label: "Name", required: true }],
      total_rows: 1, valid_rows: 0, invalid_rows: 0, created_rows: 0, updated_rows: 0, skipped_rows: 0,
      created_at: "2026-09-01T10:00:00", rows: []
    };
    let confirmed = false;
    let progressCalls = 0;
    await page.route("http://localhost:8000/api/v1/**", async (route) => {
      const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
      if (path === "/auth/me") return route.fulfill({ json: { id: 1, full_name: "Admin", email: "admin@example.com", role: "admin", is_active: true } });
      if (path === "/notifications/unread-count") return route.fulfill({ json: { unread_count: 0 } });
      if (path === "/imports") return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50, pages: 0 } });
      if (path.startsWith("/imports/templates/")) return route.fulfill({ body: "Identifier\nExample\n", contentType: "text/csv", headers: { "Content-Disposition": "attachment; filename=template.csv" } });
      if (path === "/imports/upload") return route.fulfill({ json: { ...current, headers: current.source_headers, suggested_mapping: { name: "Identifier" } }, status: 201 });
      if (path === "/imports/1/validate") {
        const request = route.request().postDataJSON();
        current = { ...current, status: "Ready", valid_rows: 1, update_mode: request.update_mode, column_mapping: request.column_mapping,
          rows: [{ id: 1, row_number: 2, status: "Valid", action: "create", mapped_data: { name: "Example" }, raw_data: { Identifier: "Example" }, errors: [], duplicate_fields: [], warnings: [{ code: "import_mileage_conflict", field: "odometer_km" }] }] };
        return route.fulfill({ json: current });
      }
      if (path === "/imports/1/confirm") {
        expect(route.request().postDataJSON().update_mode).toBe("create_or_skip");
        confirmed = true;
        current = { ...current, status: "Importing", phase: "Importing", progress_percent: 75 };
        await new Promise((resolve) => setTimeout(resolve, 1800));
        current = { ...current, status: "Completed", created_rows: 1, progress_percent: 100 };
        return route.fulfill({ json: current });
      }
      if (path === "/imports/1") {
        if (current.status === "Importing") progressCalls++;
        return route.fulfill({ json: current });
      }
      return route.fulfill({ json: [] });
    });
    await page.goto("/imports");
    await page.locator("#import-entity").selectOption(kind);
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download CSV template" }).click();
    expect((await download).suggestedFilename()).toContain("import-template");
    await page.locator("#import-file").setInputFiles({ name: "source.csv", mimeType: "text/csv", buffer: Buffer.from("Identifier\nExample\n") });
    await page.getByRole("button", { name: "Upload file", exact: true }).click();
    await expect(page.locator("#mapping-name")).toHaveValue("Identifier");
    await page.locator("#update-mode").selectOption("create_or_skip");
    await page.getByRole("button", { name: "Validate and preview" }).click();
    await expect(page.getByText("Warning:", { exact: false })).toBeVisible();
    await page.locator("table details summary").click();
    await expect(page.getByText("Example", { exact: true })).toBeVisible();
    const confirm = page.getByRole("button", { name: "Confirm import", exact: true });
    await expect(confirm).toBeEnabled();
    await page.locator("#mapping-name").selectOption("");
    await expect(confirm).toBeDisabled();
    await page.locator("#mapping-name").selectOption("Identifier");
    page.once("dialog", (dialog) => dialog.accept());
    await confirm.click();
    await expect(page.getByRole("progressbar")).toHaveAttribute("value", "75");
    await expect(page.getByText("Completed", { exact: true })).toBeVisible();
    expect(confirmed).toBe(true);
    expect(progressCalls).toBeGreaterThan(0);
  });
}

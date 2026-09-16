import { expect, test, type Page } from "@playwright/test";

async function securityApi(page: Page, role = "admin", temporary = false) {
  const state = { authenticated: true, loginError: "", reset: false, revoked: false, changed: false };
  const actor = { id: 1, email: "admin@test.local", full_name: "Security Admin", role, roles: [role], is_active: true,
    preferred_language: "en", company_id: 1, companies: [], password_reset_required: temporary };
  const users: Array<Record<string, any>> = [];
  const roles = [{ id: 1, code: "viewer", name: "Viewer", is_active: true }, { id: 2, code: "driver", name: "Driver", is_active: true }];
  await page.route("http://localhost:8000/api/v1/**", async route => {
    const request = route.request();
    expect(request.headers().authorization).toBeUndefined();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    const body = request.postData() ? request.postDataJSON() : {};
    if (path === "/auth/login") {
      if (state.loginError) return route.fulfill({ status: state.loginError === "login_rate_limited" ? 429 : 401, json: { code: state.loginError } });
      state.authenticated = true;
      return route.fulfill({ json: { user: actor } });
    }
    if (!state.authenticated) return route.fulfill({ status: 401, json: { code: "invalid_credentials" } });
    if (path === "/auth/me") return route.fulfill({ json: actor });
    if (path === "/auth/me/language") { actor.preferred_language = body.language; return route.fulfill({ json: { preferred_language: body.language } }); }
    if (path === "/auth/logout") { state.authenticated = false; return route.fulfill({ status: 204 }); }
    if (path === "/auth/me/password") {
      expect(body.current_password).toBe("temporary passphrase");
      expect(body.new_password).toBe("replacement passphrase");
      actor.password_reset_required = false;
      state.changed = true;
      return route.fulfill({ json: { user: actor } });
    }
    if (path === "/admin/users") {
      if (method === "POST") {
        expect(body.company_id).toBeUndefined();
        const created = { ...body, id: 2, roles: ["viewer"], role: "viewer", company_id: 1, password_reset_required: body.require_password_change };
        delete created.password;
        users.push(created);
        return route.fulfill({ status: 201, json: created });
      }
      return route.fulfill({ json: users });
    }
    if (path === "/admin/users/2" && method === "PUT") {
      Object.assign(users[0], body, { roles: [roles.find(r => r.id === body.role_assignments[0].role_id)!.code] });
      return route.fulfill({ json: users[0] });
    }
    if (path === "/admin/users/2/reset-password") {
      expect(body).toEqual({ temporary_password: "temporary passphrase", require_change: true });
      state.reset = true;
      return route.fulfill({ status: 204 });
    }
    if (path === "/admin/users/2/revoke-sessions") { state.revoked = true; return route.fulfill({ status: 204 }); }
    if (path === "/admin/roles") return route.fulfill({ json: roles });
    if (path === "/notifications/unread-count") return route.fulfill({ json: { unread_count: 0 } });
    if (path === "/notifications") return route.fulfill({ json: { items: [] } });
    if (path === "/dashboard/overview") return route.fulfill({ status: 503, json: { code: "api_error" } });
    return route.fulfill({ json: [] });
  });
  return { state, users, actor };
}

test("Administrator creates, assigns, changes role, deactivates, reactivates, resets and revokes", async ({ page }) => {
  const { state, users } = await securityApi(page);
  await page.goto("/admin/users");
  await page.getByRole("button", { name: "Create user", exact: true }).click();
  await page.getByLabel("Full name", { exact: true }).fill("New Driver");
  await page.getByLabel("Email", { exact: true }).fill("new@test.local");
  await page.getByLabel("Password", { exact: true }).fill("initial passphrase");
  await page.getByLabel("Role", { exact: true }).selectOption("1");
  await expect(page.getByLabel("Require password change at next login")).toBeChecked();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "New Driver new@test.local" })).toBeVisible();
  expect(users[0].password_reset_required).toBe(true);
  await expect(page.getByLabel("Password", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Role", { exact: true }).selectOption("2");
  await page.getByLabel("Active", { exact: true }).uncheck();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Inactive", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Driver", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Active", { exact: true }).check();
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("cell", { name: "Active", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByLabel("Temporary password", { exact: true }).fill("temporary passphrase");
  await page.getByRole("button", { name: "Reset password", exact: true }).click();
  await expect(page.getByText("Password reset and existing sessions revoked.")).toBeVisible();
  expect(state.reset).toBe(true);
  await expect(page.getByLabel("Temporary password", { exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Force logout", exact: true }).click();
  await expect(page.getByText("All sessions revoked.")).toBeVisible();
  expect(state.revoked).toBe(true);
  await page.getByLabel("Language", { exact: true }).selectOption("sq");
  await expect(page.getByRole("heading", { name: "Administrimi i Përdoruesve" })).toBeVisible();
});

test("Temporary password redirects direct navigation and changes with confirmation", async ({ page }) => {
  const { state } = await securityApi(page, "viewer", true);
  await page.goto("/vehicles");
  await expect(page).toHaveURL(/\/account\/password$/);
  await page.getByLabel("Current password", { exact: true }).fill("temporary passphrase");
  await page.getByLabel("New password", { exact: true }).fill("replacement passphrase");
  await page.getByLabel("Confirm password", { exact: true }).fill("incorrect passphrase");
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  await expect(page.getByText("The new passwords do not match.")).toBeVisible();
  await page.getByLabel("Confirm password", { exact: true }).fill("replacement passphrase");
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  expect(state.changed).toBe(true);
});

test("Expired session redirects and generic login/cooldown errors are localized", async ({ page }) => {
  const { state } = await securityApi(page);
  await page.goto("/admin/users");
  state.authenticated = false;
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  state.loginError = "invalid_credentials";
  await page.getByLabel("Email", { exact: true }).fill("unknown@test.local");
  await page.getByLabel("Password", { exact: true }).fill("incorrect passphrase");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page.getByText("Invalid email or password.")).toBeVisible();
  state.loginError = "login_rate_limited";
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page.getByText("Too many login attempts. Please try again later.")).toBeVisible();
  await page.getByLabel("Language", { exact: true }).selectOption("sq");
  await page.getByRole("button", { name: "Hyr", exact: true }).click();
  await expect(page.getByText("Shumë tentativa për hyrje. Ju lutemi provoni përsëri më vonë.")).toBeVisible();
  state.loginError = "invalid_credentials";
  await page.getByRole("button", { name: "Hyr", exact: true }).click();
  await expect(page.getByText("Email-i ose fjalëkalimi është i pasaktë.")).toBeVisible();
});

test("Logout clears session view and old token while retaining language", async ({ page }) => {
  const { state } = await securityApi(page);
  await page.addInitScript(() => localStorage.setItem("vehicle_fleet_control_token", "obsolete-token"));
  await page.goto("/admin/users");
  await page.getByLabel("Language", { exact: true }).selectOption("sq");
  await page.locator(".logoutButton").click();
  await expect(page).toHaveURL(/\/login$/);
  expect(state.authenticated).toBe(false);
  await expect(page.locator("html")).toHaveAttribute("lang", "sq");
  expect(await page.evaluate(() => localStorage.getItem("vehicle_fleet_control_token"))).toBeNull();
});

test("Viewer cannot see user actions or use direct administration navigation", async ({ page }) => {
  await securityApi(page, "viewer");
  await page.goto("/admin/users");
  await expect(page.getByText("You do not have permission to view this page.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create user", exact: true })).toHaveCount(0);
  await expect(page.locator('nav a[href="/admin/users"]')).toHaveCount(0);
});

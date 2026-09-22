import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { expect, test } from "@playwright/test";

let server: ChildProcess;
let api: string;

test.beforeAll(async () => {
  const backend = path.resolve(process.cwd(), "../backend");
  server = spawn(path.join(backend, ".venv/bin/python"), ["-m", "tests.auth_browser_server"], {
    cwd: backend,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", ENVIRONMENT: "development", COOKIE_SECURE: "false",
      DATABASE_URL: "sqlite://", CORS_ORIGINS: "http://localhost:3000", JWT_SECRET_KEY: "ephemeral-browser-test-secret-only" }
  });
  let errors = "";
  server.stderr?.on("data", chunk => { errors += String(chunk); });
  const port = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`Isolated API startup timeout: ${errors}`)), 15_000);
    server.stdout?.on("data", chunk => {
      const match = /AUTH_TEST_PORT=(\d+)/.exec(String(chunk));
      if (match) { clearTimeout(timeout); resolve(match[1]); }
    });
    server.on("exit", code => { clearTimeout(timeout); reject(new Error(`Isolated API exited ${code}: ${errors}`)); });
  });
  api = `http://127.0.0.1:${port}`;
  await expect.poll(async () => { try { return (await fetch(`${api}/health`)).status; } catch { return 0; } }).toBe(200);
});

test.afterAll(async () => {
  if (server && server.exitCode === null) {
    await new Promise<void>(resolve => { server.once("exit", () => resolve()); server.kill("SIGTERM"); });
  }
});

test("Real FastAPI cookie survives reload, is unreadable to JavaScript, rejects CSRF and is revoked on logout", async ({ page, context }) => {
  // Preserve the browser-visible same-site URL and forward to the isolated API.
  await page.route("http://localhost:8000/api/v1/**", async route => {
    const source = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${source.pathname}${source.search}` });
    await route.fulfill({ response });
  });
  await page.goto("http://localhost:3000/login");
  await page.getByLabel("Email", { exact: true }).fill("browser@test.local");
  await page.getByLabel("Password", { exact: true }).fill("test-only browser passphrase");
  await page.getByRole("button", { name: "Login", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.locator(".userName")).toHaveText("Browser Admin");
  const cookie = (await context.cookies("http://localhost:8000")).find(row => row.name === "vehicle_fleet_control_session")!;
  expect(cookie).toBeDefined();
  expect(cookie.httpOnly).toBe(true);
  expect(cookie.sameSite).toBe("Lax");
  expect(cookie.path).toBe("/");
  expect(await page.evaluate(() => document.cookie)).not.toContain("vehicle_fleet_control_session");
  expect(await page.evaluate(() => localStorage.getItem("vehicle_fleet_control_token"))).toBeNull();
  const restoredSession = page.waitForResponse(response =>
    response.url() === "http://localhost:8000/api/v1/auth/me" && response.request().method() === "GET"
  );
  await page.reload();
  expect((await restoredSession).status()).toBe(200);
  await expect(page.locator(".userName")).toHaveText("Browser Admin", { timeout: 15_000 });
  const csrf = await context.request.post(`${api}/api/v1/auth/logout`, {
    headers: { Origin: "https://untrusted.example", Cookie: `${cookie.name}=${cookie.value}` }
  });
  expect(csrf.status()).toBe(403);
  await page.locator(".logoutButton").click();
  await expect(page).toHaveURL(/\/login$/);
  expect((await context.cookies("http://localhost:8000")).find(row => row.name === cookie.name)).toBeUndefined();
  const replay = await context.request.get(`${api}/api/v1/auth/me`, { headers: { Cookie: `${cookie.name}=${cookie.value}` } });
  expect(replay.status()).toBe(401);
});

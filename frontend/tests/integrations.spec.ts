import { expect, test, type Page } from "@playwright/test";

async function mockIntegrations(page: Page, allowed = true) {
  const keys: Array<Record<string, unknown>> = [];
  const endpoints: Array<Record<string, unknown>> = [];
  const deliveries: Array<Record<string, unknown>> = [{id:1, delivery_id:"delivery-one", event_id:"event-one", event_type:"fuel.created", status:"Dead", payload:JSON.stringify({event_id:"event-one",event_type:"fuel.created",company_id:1,entity_id:4,data:{}}),attempt_count:6,attempts:[{number:1,started_at:"2026-09-17T10:00:00Z",outcome:"HTTPError",http_status:503,secret_version:1}],next_attempt_at:"2026-09-17T10:01:00",resend_of:null}];
  const state = { retry: false };
  await page.route("http://localhost:8000/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const method = request.method();
    const body = request.postData() ? request.postDataJSON() : {};
    if (path === "/auth/me") return route.fulfill({ json: {id:1, email:"admin@test.local", full_name:"Admin", role:"admin", is_active:true, company_id:1, companies:[], preferred_language:"en", permissions:allowed ? ["integrations.manage"] : []} });
    if (path === "/notifications/unread-count") return route.fulfill({json:{unread_count:0}});
    if (path === "/notifications") return route.fulfill({json:{items:[]}});
    const base = "/admin/integrations";
    if (path === `${base}/options`) return route.fulfill({json:{scopes:["vehicles.read", "fuel.write"],events:["fuel.created", "vehicle.created"]}});
    if (path === `${base}/api-keys`) {
      if (method === "POST") {
        expect(body.company_id).toBeUndefined();
        const row = {id:1,...body,key_prefix:"vfc_prefix",created_at:"2026-09-17T10:00:00",last_used_at:null,revoked_at:null};
        keys.push(row); return route.fulfill({status:201,json:{...row,raw_key:"vfc_once_only_secret"}});
      }
      return route.fulfill({json:keys});
    }
    if (path === `${base}/api-keys/1/rotate`) return route.fulfill({json:{...keys[0],raw_key:"vfc_rotated_secret"}});
    if (path === `${base}/api-keys/1/revoke`) { keys[0].revoked_at="2026-09-17T11:00:00"; return route.fulfill({json:keys[0]}); }
    if (path === `${base}/webhooks`) {
      if (method === "POST") { const row={id:1,...body,secret_version:1,revoked_at:null,created_at:"2026-09-17T10:00:00"}; endpoints.push(row); return route.fulfill({status:201,json:{...row,secret:"whsec_once_only"}}); }
      return route.fulfill({json:endpoints});
    }
    if (path === `${base}/webhooks/1/rotate`) { endpoints[0].secret_version=2; return route.fulfill({json:{...endpoints[0],secret:"whsec_rotated"}}); }
    if (path === `${base}/webhooks/1/deliveries`) return route.fulfill({json:deliveries});
    if (path === `${base}/deliveries/1/retry`) { state.retry=true; const row={...deliveries[0],id:2,delivery_id:"delivery-two",status:"Pending",attempts:[],attempt_count:0,resend_of:1};deliveries.unshift(row);return route.fulfill({status:201,json:row}); }
    return route.fulfill({json:[]});
  });
  return state;
}

test("API keys show secrets once, rotate, and revoke", async ({page}) => {
  await mockIntegrations(page);
  await page.goto("/admin/integrations/api-keys");
  await page.getByLabel("Name", {exact:true}).fill("Accounting");
  await page.getByLabel("vehicles.read", {exact:true}).check();
  await page.getByRole("button", {name:"Create",exact:true}).click();
  await expect(page.getByText("vfc_once_only_secret",{exact:true})).toBeVisible();
  await page.getByRole("button", {name:"Dismiss secret"}).click();
  await expect(page.getByText("vfc_once_only_secret",{exact:true})).toHaveCount(0);
  await page.getByRole("button", {name:"Rotate",exact:true}).click();
  await expect(page.getByText("vfc_rotated_secret",{exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByText("vfc_rotated_secret",{exact:true})).toHaveCount(0);
  await page.getByRole("button", {name:"Revoke",exact:true}).click();
  await expect(page.getByRole("button", {name:"Rotate",exact:true})).toBeDisabled();
  await expect(page.getByText("Revoked",{exact:true})).toBeVisible();
});

test("Webhooks create, rotate, inspect immutable history and resend", async ({page}) => {
  const state = await mockIntegrations(page);
  await page.goto("/admin/integrations/webhooks");
  await page.getByLabel("Name",{exact:true}).fill("Accounting hook");
  await page.getByLabel("Webhook URL").fill("https://example.com/events");
  await page.getByLabel("fuel.created",{exact:true}).check();
  await page.getByRole("button",{name:"Create",exact:true}).click();
  await expect(page.getByText("whsec_once_only",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Rotate",exact:true}).click();
  await expect(page.getByText("whsec_rotated",{exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Inspect deliveries",exact:true}).click();
  await page.getByText("fuel.created · Dead · delivery-one",{exact:true}).click();
  await expect(page.getByText(/HTTP error · 503/)).toBeVisible();
  await page.getByRole("button",{name:"Resend",exact:true}).click();
  await expect(page.getByText("fuel.created · Pending · delivery-two",{exact:true})).toBeVisible();
  await expect(page.getByText("fuel.created · Dead · delivery-one",{exact:true})).toBeVisible();
  expect(state.retry).toBe(true);
});

test("Integrations are hidden without permission", async ({page}) => {
  await mockIntegrations(page,false);
  await page.goto("/admin/integrations/api-keys");
  await expect(page.getByRole("button",{name:"Create",exact:true})).toHaveCount(0);
  await expect(page.getByRole("link",{name:"Integrations",exact:true})).toHaveCount(0);
});

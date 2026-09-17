import { expect, test, type Page } from "@playwright/test";
const record = {id: 7, vehicle_id: 1, driver_id: 3, created_by_user_id: 1, license_plate: "01-111-AA", vehicle_name: "VW Golf",
  inspection_type: "Daily", inspection_date: "17-09-2026", updated_at: "2026-09-17T08:00:00", created_at: "2026-09-17T08:00:00",
  template_id: 1, template_snapshot: {name: "Daily safety"}, archived: false, items: [{id: 11, item_name: "Brakes", status: "Not Checked", comment: "", photo_attachment_ids: [], item_snapshot: {required:true}}]};
async function mock(page: Page, role = "driver") {
  const state = {online: true, expired: false, conflict: false, photoFailures: 0, uploads: 0, completions: 0, accidents: 0, payloads: [] as any[]};
  const user = {id:1, company_id:1, driver_id:3, email:"driver@test.local",full_name:"Alex Field",role,roles:[role],companies:[],is_active:true,preferred_language:"en",
    permissions: ["dashboard.view","vehicles.view","assignments.view","assignments.self_service","inspections.view","inspections.create","accidents.view","accidents.report","maintenance.report_issue","maintenance.view","documents.view","reservations.view",
      ...(role === "mechanic" ? ["labor.manage","inventory.manage","maintenance.assign_work_order","maintenance.complete_work_order"] : [])]};
  await page.route("http://localhost:8000/api/v1/**", async route => {
    if(!state.online) return route.abort("internetdisconnected");
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if(state.expired) return route.fulfill({status:401,json:{message:"Session expired"}});
    if(path === "/auth/me") return route.fulfill({json:user});
    if(path === "/auth/me/language") {user.preferred_language=route.request().postDataJSON().language;return route.fulfill({json:{preferred_language:user.preferred_language}});}
    if(path === "/auth/logout") {state.expired=true;return route.fulfill({status:204});}
    if(path === "/mobile/home") return route.fulfill({json:{driver_id:3,vehicles:[{id:1,license_plate:"01-111-AA",name:"VW Golf",odometer_km:12000}],assignments:[],reservations:[],
      orders:role === "mechanic" ? [{id:4,title:"Repair brakes",status:"In Progress",priority:"Critical"},{id:5,title:"Replace filter",status:"Waiting for Parts",priority:"High"}] : []}});
    if(path === "/mobile/sync") {
      const body = route.request().postDataJSON();state.payloads.push(body);
      if(body.kind === "prepare") return route.fulfill({json:record});
      if(body.kind === "accident") {state.accidents++;return route.fulfill({json:{id:19}});}
      state.completions++;
      if(state.conflict) return route.fulfill({status:409,json:{message:"Inspection changed on the server"}});
      return route.fulfill({json:{...record,completed_at:"2026-09-17T09:00:00"}});
    }
    if(path === "/mobile/photos") {state.uploads++;if(state.photoFailures-- > 0) return route.abort("failed");return route.fulfill({json:{id:21}});}
    if(path === "/mobile/inspections/7") return route.fulfill({json:{...record,items:[{...record.items[0],status:"Fail",comment:"Server found damage"}]}});
    if(path === "/notifications/unread-count") return route.fulfill({json:{unread_count:0}});
    if(path === "/notifications") return route.fulfill({json:{items:[]}});
    return route.fulfill({json:[]});
  });
  return {state,user};
}
async function ready(page: Page) {
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await expect.poll(() => page.evaluate(() => Boolean(navigator.serviceWorker.controller))).toBe(true);
}
async function prepare(page: Page) {
  await page.goto("/mobile");await ready(page);
  await page.getByRole("button",{name:"Download template / start inspection"}).click();
  await expect(page.getByRole("heading",{name:"Offline workspace"})).toBeVisible();
  await expect(page.getByRole("combobox",{name:"Result",exact:true})).toBeVisible();
}
async function readDrafts(page: Page) {
  return page.evaluate(async () => new Promise<any[]>((resolve,reject) => {const req=indexedDB.open("vfc-mobile-v1",1);req.onsuccess=()=>{const db=req.result;const q=db.transaction("drafts").objectStore("drafts").getAll();q.onsuccess=()=>{resolve(q.result);db.close();};q.onerror=()=>reject(q.error);};}));
}

test("mobile driver landing, permission gates, Albanian and install metadata", async ({page}) => {
  const {user} = await mock(page);await page.goto("/dashboard");await expect(page).toHaveURL(/\/mobile$/);
  await expect(page.getByRole("heading",{name:"My day"})).toBeVisible();
  await expect(page.getByRole("link",{name:"Users",exact:true})).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const manifest = await (await page.request.get("/manifest.webmanifest")).json();
  expect(manifest.display).toBe("standalone");expect(manifest.start_url).toBe("/mobile");
  for(const icon of manifest.icons) expect((await page.request.get(icon.src)).status()).toBe(200);
  await ready(page);
  const cdp = await page.context().newCDPSession(page);
  const eligibility = await cdp.send("Page.getInstallabilityErrors");
  expect(eligibility.installabilityErrors).toEqual([]);
  await page.screenshot({path: "test-results/mobile-driver.png", fullPage: true});
  const caches = await page.evaluate(async () => {const urls=[];for(const name of await window.caches.keys()) for(const r of await (await window.caches.open(name)).keys()) urls.push(r.url);return urls;});
  expect(caches.some(url=>url.includes("/api/v1"))).toBe(false);
  expect(caches.some(url=>url.endsWith("/mobile/offline"))).toBe(true);
  await page.getByLabel("Language",{exact:true}).selectOption("sq");await expect(page.getByRole("heading",{name:"Dita ime"})).toBeVisible();
  user.permissions=user.permissions.filter(p=>p!=="accidents.report" && p!=="assignments.self_service");
  await page.reload();await expect(page.getByRole("button",{name:"Raporto aksident",exact:true})).toHaveCount(0);
});

test("technician has own orders and direct parts, labor and photo actions", async ({page}) => {
  await mock(page,"mechanic");await page.goto("/mobile");
  await expect(page.getByRole("heading",{name:"My work orders"})).toBeVisible();
  await expect(page.getByRole("link",{name:"Clock in / out"}).first()).toHaveAttribute("href","/work-orders/4?tab=Labor");
  await expect(page.getByRole("link",{name:"Add part"}).first()).toHaveAttribute("href","/work-orders/4?tab=Parts");
  await expect(page.getByRole("link",{name:"Add photo"}).first()).toHaveAttribute("href","/work-orders/4?tab=Attachments");
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:"test-results/mobile-technician.png",fullPage:true});
});

test("offline inspection survives reload with photos, then synchronizes once", async ({page,context}) => {
  const {state}=await mock(page);await prepare(page);state.online=false;await context.setOffline(true);
  await page.getByRole("combobox",{name:"Result",exact:true}).selectOption("Pass");await page.getByRole("textbox",{name:"Comment",exact:true}).fill("Checked at depot");
  await page.getByLabel("Add photo",{exact:true}).setInputFiles("public/icons/icon-192.png");
  await expect.poll(async()=> (await readDrafts(page))[0].photos.length).toBe(1);
  await page.getByRole("button",{name:"Save locally",exact:true}).click();await page.reload();
  await page.goto("/mobile");await expect(page).toHaveURL(/\/mobile\/offline$/);
  await expect(page.getByRole("textbox",{name:"Comment",exact:true})).toHaveValue("Checked at depot");
  await page.getByRole("button",{name:"Queue for synchronization"}).click();
  await expect(page.getByText("Pending Sync",{exact:true})).toBeVisible();
  state.online=true;await context.setOffline(false);
  await expect(page.getByText("Synced",{exact:true})).toBeVisible({timeout:20000});
  expect(state.uploads).toBe(1);expect(state.completions).toBe(1);
  expect(state.payloads.at(-1).payload.items[0].photo_attachment_ids).toEqual([21]);
  expect((await readDrafts(page))[0].photos).toEqual([]);
  await page.getByRole("button",{name:"Synchronize now"}).click();expect(state.completions).toBe(1);
});

test("server conflict keeps local results and requires review", async ({page}) => {
  const {state}=await mock(page);await prepare(page);state.conflict=true;
  await page.getByRole("combobox",{name:"Result",exact:true}).selectOption("Pass");await page.getByRole("textbox",{name:"Comment",exact:true}).fill("Local evidence");
  await page.getByRole("button",{name:"Queue for synchronization"}).click();await page.getByRole("button",{name:"Synchronize now"}).click();
  await expect(page.getByText("Conflict",{exact:true})).toBeVisible();await expect(page.getByRole("textbox",{name:"Comment",exact:true})).toHaveValue("Local evidence");
  await page.getByRole("button",{name:"Review server version"}).click();await expect(page.getByText(/Server found damage/)).toBeVisible();
  const count=state.completions;await page.getByRole("button",{name:"Synchronize now"}).click();expect(state.completions).toBe(count);
});

test("photo retries persist and an expired session cannot submit", async ({page}) => {
  const {state}=await mock(page);await prepare(page);
  await page.getByRole("combobox",{name:"Result",exact:true}).selectOption("Pass");await page.getByLabel("Add photo",{exact:true}).setInputFiles("public/icons/icon-192.png");
  await expect.poll(async()=> (await readDrafts(page))[0].photos.length).toBe(1);
  await page.getByRole("button",{name:"Queue for synchronization"}).click();state.expired=true;
  await page.getByRole("button",{name:"Synchronize now"}).click();await expect(page.getByRole("alert").filter({hasText:"Sign in again"})).toBeVisible();
  expect(state.uploads).toBe(0);expect((await readDrafts(page))[0].status).toBe("Pending Sync");
  state.expired=false;state.photoFailures=1;await page.getByRole("button",{name:"Synchronize now"}).click();
  await expect(page.getByText("Failed",{exact:true})).toBeVisible();expect((await readDrafts(page))[0].photos[0].blob).toBeTruthy();
  await page.getByRole("button",{name:"Synchronize now"}).click();await expect(page.getByText("Synced",{exact:true})).toBeVisible();
  expect(state.uploads).toBe(2);expect(state.completions).toBe(1);
});

test("new accident from saved vehicle works offline and submits after reconnect", async ({page,context}) => {
  const {state}=await mock(page);await page.goto("/mobile");await ready(page);
  await page.getByRole("button",{name:"Save vehicle for offline accident reports"}).click();
  await expect(page.getByRole("button",{name:"New offline accident report"})).toBeVisible();
  state.online=false;await context.setOffline(true);await page.reload();
  await page.getByRole("button",{name:"New offline accident report"}).click();
  await page.getByLabel("Location",{exact:true}).fill("Depot gate");await page.getByLabel("Description",{exact:true}).fill("Left panel damaged");
  await page.getByRole("button",{name:"Queue for synchronization"}).click();state.online=true;await context.setOffline(false);
  await expect(page.getByText("Synced",{exact:true})).toBeVisible({timeout:20000});expect(state.accidents).toBe(1);
});

test("service worker update waits for approval and preserves unsaved editor", async ({page}) => {
  await mock(page);await prepare(page);await page.getByRole("textbox",{name:"Comment",exact:true}).fill("Unsaved during update");
  // A changed script URL starts a genuine second worker while the first controls the page.
  await page.evaluate(async()=> {await navigator.serviceWorker.register("/sw.js?revision=update-test",{scope:"/",updateViaCache:"none"});});
  await expect(page.getByRole("button",{name:"Activate update"})).toBeVisible({timeout:20000});
  await page.getByRole("button",{name:"Activate update"}).click();
  await expect(page.getByRole("textbox",{name:"Comment",exact:true})).toHaveValue("Unsaved during update");
});


test("company switching isolates saved work and explicit logout clears drafts", async ({page}) => {
  const {user,state}=await mock(page);await prepare(page);
  await page.getByRole("textbox",{name:"Comment",exact:true}).fill("Private company A note");
  await page.getByRole("button",{name:"Save locally",exact:true}).click();
  await expect.poll(async()=>(await readDrafts(page))[0].payload.items[0].comment).toBe("Private company A note");
  user.company_id=2;await page.reload();
  await expect(page.getByRole("heading",{name:"01-111-AA",exact:true})).toHaveCount(0);
  expect((await readDrafts(page)).length).toBe(1);expect(state.completions).toBe(0);
  user.company_id=1;await page.reload();await expect(page.getByRole("textbox",{name:"Comment",exact:true})).toHaveValue("Private company A note");
  await page.goto("/mobile");await page.getByRole("button",{name:"Open navigation"}).click();
  await page.getByRole("button",{name:"Logout",exact:true}).click();
  await expect(page).toHaveURL(/\/login$/);expect(await readDrafts(page)).toEqual([]);
});

import { expect, test, type Page } from "@playwright/test";
import type { Assignment, Schedule, Template } from "../src/lib/inspection-templates";

async function mock(page: Page, role = "admin") {
  const rows: Template[] = [];
  const assignments: Assignment[] = [];
  const schedules: Schedule[] = [];
  await page.addInitScript(() => localStorage.setItem("vehicleFleetControl.language", "en"));
  await page.route("http://localhost:8000/api/v1/**", async route => {
    const req = route.request(); const path = new URL(req.url()).pathname.replace("/api/v1", ""); const method = req.method();
    const body = ["GET", "DELETE"].includes(method) ? {} : req.postDataJSON();
    if (path === "/auth/me") return route.fulfill({json: {id: 1, email: "admin@test.local", full_name: "Admin", role, is_active: true, preferred_language: "en"}});
    if (path === "/auth/me/language") return route.fulfill({json: {preferred_language: body.language}});
    if (path === "/notifications/unread-count") return route.fulfill({json: {unread_count: 0}});
    if (path === "/inspection-templates/options") return route.fulfill({json: {vehicles: [{id: 1, name: "01-111-AA"}], locations: [{id:1,name:"Depot"}], departments: [], brands: ["VW"], models:[{brand:"VW",model:"Golf"}], fuel_types:["Diesel"], vehicle_categories:["Passenger"]}});
    if (path === "/inspection-templates") {
      if (method === "POST") { const row = {...body, id: rows.length + 1, archived: false, items: []}; rows.push(row); return route.fulfill({json: row}); }
      return route.fulfill({json: rows});
    }
    const parts = path.split("/"); const row = rows.find(r => r.id === Number(parts[2]));
    if (row) {
      if (parts[3] === "assignments") {
        if (method === "POST") {assignments.push({...body,id:assignments.length+1}); return route.fulfill({json: assignments.at(-1)});}
        return route.fulfill({json: assignments});
      }
      if (parts[3] === "schedules") {
        if (method === "POST") {schedules.push({...body,id:schedules.length+1}); return route.fulfill({json: schedules.at(-1)});}
        return route.fulfill({json: schedules});
      }
      if (parts[3] === "items") {
        if (parts[4] === "reorder") {row.items = body.item_ids.map((id:number,display_order:number) => ({...row.items.find(i => i.id===id),display_order})); return route.fulfill({json:row});}
        if (method === "POST") {row.items.push({...body,id:row.items.length+1}); return route.fulfill({json:row.items.at(-1)});}
        if (method === "DELETE") {row.items = row.items.filter(i => i.id !== Number(parts[4])); return route.fulfill({json:{deleted:true}});}
        if (method === "PUT") {row.items = row.items.map(i => i.id===Number(parts[4]) ? {...body,id:i.id} : i); return route.fulfill({json:row.items.find(i=>i.id===Number(parts[4]))});}
      }
      if (parts[3] === "duplicate") {const copy = {...body,id:rows.length+1,archived:false,items:row.items.map(i=>({...i}))}; rows.push(copy); return route.fulfill({json:copy});}
      if (parts[3] === "archive") row.archived = true;
      if (parts[3] === "restore") row.archived = false;
      if (parts.length === 3 && method === "PUT") Object.assign(row,body);
      return route.fulfill({json: row});
    }
    return route.fulfill({status:404,json:{message:`Unmocked ${path}`}});
  });
  return {rows,assignments,schedules};
}

test("Admin configures, reorders, previews, duplicates and restores a template in both languages", async ({page}) => {
  const state = await mock(page);
  await page.goto("/admin/inspection-templates");
  await expect(page.getByRole("heading",{name:"Inspection Templates",exact:true})).toBeVisible();
  await page.getByLabel("Start with a template name").selectOption("daily");
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Add item",exact:true})).toBeVisible();
  const itemForm = page.locator("form").filter({has:page.getByRole("heading",{name:"Add item",exact:true})});
  await itemForm.getByLabel("Code",{exact:true}).fill("BRAKES");
  await itemForm.getByLabel("Name",{exact:true}).fill("Brake pads");
  await itemForm.getByLabel("Critical failure",{exact:true}).check();
  await itemForm.getByLabel("Photo required on failure",{exact:true}).check();
  await itemForm.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("cell",{name:"Brake pads BRAKES"})).toBeVisible();
  await itemForm.getByLabel("Code",{exact:true}).fill("TIRES");
  await itemForm.getByLabel("Name",{exact:true}).fill("Tire pressure");
  await itemForm.getByRole("button",{name:"Save",exact:true}).click();
  await expect(page.getByRole("cell",{name:"Tire pressure TIRES"})).toBeVisible();
  await page.getByRole("button",{name:"Move item up"}).nth(1).click();
  await expect.poll(() => state.rows[0].items[0].code).toBe("TIRES");
  const assignmentForm = page.locator("form").filter({has:page.getByRole("combobox",{name:"Applies to",exact:true})});
  await assignmentForm.getByRole("combobox",{name:"Selection",exact:true}).selectOption("1");
  await assignmentForm.getByRole("button",{name:"Save",exact:true}).click();
  await expect.poll(() => state.assignments.length).toBe(1);
  expect(state.assignments[0]).toMatchObject({target_type:"Vehicle",target_value:"1"});
  const scheduleForm = page.locator("form").filter({has:page.getByRole("combobox",{name:"Frequency",exact:true})});
  await scheduleForm.getByRole("combobox",{name:"Frequency",exact:true}).selectOption("Every X days");
  await scheduleForm.getByLabel("Interval in days").fill("3");
  await scheduleForm.getByRole("button",{name:"Save",exact:true}).click();
  await expect.poll(() => state.schedules.length).toBe(1);
  expect(state.schedules[0].interval_days).toBe(3);
  await page.getByRole("button",{name:"Preview",exact:true}).click();
  await expect(page.getByRole("heading",{name:"Preview · Daily Inspection"})).toBeVisible();
  await page.screenshot({path:"/tmp/inspection-templates-admin.png",fullPage:true});
  await page.getByRole("button",{name:"Archive",exact:true}).click();
  await expect(page.getByRole("button",{name:"Restore",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Restore",exact:true}).click();
  await expect(page.getByRole("button",{name:"Archive",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Duplicate",exact:true}).click();
  await page.getByRole("button",{name:"Save",exact:true}).click();
  await expect.poll(() => state.rows.length).toBe(2);
  expect(state.rows[1].items).toHaveLength(2);
  await page.getByLabel("Language",{exact:true}).selectOption("sq");
  await expect(page.getByRole("heading",{name:"Modelet e inspektimit",exact:true})).toBeVisible();
});

test("A viewer cannot configure templates", async ({page}) => {
  await mock(page,"viewer"); await page.goto("/admin/inspection-templates");
  await expect(page.getByText("You do not have permission to configure inspection templates.")).toBeVisible();
  await expect(page.getByRole("button",{name:"Create template",exact:true})).toHaveCount(0);
});

for (const role of ["admin", "driver"]) test(`Result completion submits immutable snapshot IDs and names for ${role}`, async ({page}) => {
  await mock(page, role);
  let submitted: Record<string,unknown> | null = null;
  const inspection = {id:1,created_by_user_id:1,vehicle_id:1,license_plate:"01-111-AA",vehicle_name:"VW Golf",inspection_type:"Daily",inspection_date:"14-09-2026",overall_status:"Needs Review",template_id:1,template_snapshot:{name:"Daily – original",description:"Original rules"},completed_at:null as string|null,items:[{id:12,item_name:"Original brake wording",status:"Not Checked",comment:"",photo_attachment_ids:[],item_snapshot:{name:"Original brake wording",category:"Brakes",required:true,critical:true}}],archived:false};
  await page.route("http://localhost:8000/api/v1/inspections/1", async route => {
    if (route.request().method() === "PUT") {submitted=route.request().postDataJSON(); inspection.completed_at="2026-09-14T12:00:00";inspection.overall_status="Passed"; inspection.items[0].status="Pass";}
    return route.fulfill({json:inspection});
  });
  await page.goto("/inspections/1");
  await expect(page.getByText("Original brake wording",{exact:true})).toBeVisible();
  await page.getByRole("combobox",{name:"Status",exact:true}).selectOption("Pass");
  await page.getByRole("button",{name:"Complete inspection",exact:true}).click();
  await expect(page.getByText("Completed. Results and checklist are locked.")).toBeVisible();
  expect(submitted).toMatchObject({complete:true,items:[{id:12,item_name:"Original brake wording",status:"Pass"}]});
  await expect(page.getByRole("button",{name:"Complete inspection",exact:true})).toHaveCount(0);
});

test("Beginning a resolved inspection saves a snapshot before collecting results", async ({page}) => {
  await mock(page);
  let submitted: Record<string,unknown> | null = null;
  await page.route("http://localhost:8000/api/v1/vehicles", route => route.fulfill({json:[{id:1,license_plate:"01-111-AA",brand:"VW",model:"Golf"}]}));
  await page.route("http://localhost:8000/api/v1/inspection-templates/resolve?**", route => route.fulfill({json:{id:5,name:"Resolved Daily",items:[{id:8,name:"Saved brake policy"}]}}));
  await page.route("http://localhost:8000/api/v1/inspections?**", route => route.fulfill({json:{items:[],page:1,page_size:20,total:0,pages:0}}));
  const saved = {id:2,vehicle_id:1,inspection_type:"Daily",inspection_date:"14-09-2026",overall_status:"Needs Review",template_id:5,template_snapshot:{name:"Resolved Daily"},items:[{id:88,item_name:"Saved brake policy",status:"Not Checked"}],archived:false};
  await page.route("http://localhost:8000/api/v1/inspections", async route => {submitted=route.request().postDataJSON(); return route.fulfill({json:saved});});
  await page.route("http://localhost:8000/api/v1/inspections/2", route => route.fulfill({json:saved}));
  await page.goto("/inspections");
  await page.locator("form").getByRole("combobox").first().selectOption("1");
  await expect(page.getByRole("heading",{name:"Resolved Daily",exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Begin inspection",exact:true}).click();
  await expect(page).toHaveURL(/\/inspections\/2$/);
  expect(submitted).toMatchObject({vehicle_id:1,template_id:5,items:[]});
  await expect(page.getByText("Saved brake policy",{exact:true})).toBeVisible();
});

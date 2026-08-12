export const VEHICLE_STATUS_KEYS: Record<number, string> = {
  0: "status.Active",
  1: "status.In Service",
  2: "status.Sold",
  3: "status.Out of Use",
  4: "status.Assigned"
};

export const VEHICLE_STATUSES = [
  { value: 0, labelKey: "status.Active" },
  { value: 1, labelKey: "status.In Service" },
  { value: 2, labelKey: "status.Sold" },
  { value: 3, labelKey: "status.Out of Use" }
];

export const RESERVATION_STATUS_KEYS: Record<number, string> = {
  0: "status.Pending",
  1: "status.Approved",
  2: "status.Rejected",
  3: "status.Cancelled",
  4: "status.Completed"
};

export const RESERVATION_STATUSES = [
  { value: 0, labelKey: "status.Pending" },
  { value: 1, labelKey: "status.Approved" },
  { value: 2, labelKey: "status.Rejected" },
  { value: 3, labelKey: "status.Cancelled" },
  { value: 4, labelKey: "status.Completed" }
];

export const FUEL_TYPES = ["Petrol", "Diesel", "Hybrid", "Electric", "LPG", "CNG", "Gas"];
export const ENERGY_UNITS = ["L", "KWH"] as const;
export const OWNERSHIP_TYPES = ["Owned", "Leased", "Rented", "Financed"] as const;
export const DEPRECIATION_METHODS = ["Straight Line", "Declining Balance", "None"] as const;
export const SERVICE_TYPES = ["General Service", "Oil Change", "Tire Change/Control", "Part Change", "Maintenance", "Other"];
export const SERVICE_KM_INTERVALS = [5000, 10000, 15000];
export const DOCUMENT_TYPES = ["Registration", "Insurance", "Technical Control", "Ownership", "Other"];
export const RESERVATION_TYPES = ["Business Trip", "Personal Use", "Replacement Vehicle", "Maintenance", "Other"];
export const DRIVER_STATUSES = ["Active", "Suspended", "Left Company"];
export const INSPECTION_TYPES = [
  "General",
  "Daily",
  "Weekly",
  "Monthly",
  "Before Trip",
  "After Trip",
  "Random",
  "Return Inspection"
];
export const INSPECTION_ITEM_STATUSES = ["Pass", "Fail", "Not Checked"];
export const INSPECTION_OVERALL_STATUSES = ["Passed", "Failed", "Needs Review"];
export const DEFAULT_INSPECTION_ITEMS = [
  "Tires",
  "Lights",
  "Brakes",
  "Oil level",
  "Coolant level",
  "Windshield",
  "Mirrors",
  "Body damage",
  "Interior condition",
  "Fuel level",
  "Warning lights",
  "Documents present",
  "Spare tire/tools"
];
export const WORK_ORDER_STATUSES = ["Open", "Assigned", "In Progress", "Waiting for Parts", "Completed", "Cancelled"];
export const WORK_ORDER_PRIORITIES = ["Low", "Medium", "High", "Critical"];
export const WORK_ORDER_SOURCES = ["Manual", "Inspection", "Service Reminder", "Breakdown", "Accident", "Other"];
export const SERVICE_SOURCES = ["Manual", "Work Order", "Imported"];
export const REMINDER_STATUSES = ["Upcoming", "Due Soon", "Due", "Overdue", "Resolved", "Dismissed"];
export const REPORTS = [
  { value: "fleet-summary", labelKey: "reports.fleet-summary" },
  { value: "fuel-costs", labelKey: "reports.fuel-costs" },
  { value: "service-costs", labelKey: "reports.service-costs" },
  { value: "vehicle-costs", labelKey: "reports.vehicle-costs" },
  { value: "reservations", labelKey: "reports.reservations" },
  { value: "document-expiry", labelKey: "reports.document-expiry" },
  { value: "document-compliance", labelKey: "reports.document-compliance" },
  { value: "work-orders", labelKey: "reports.work-orders" },
  { value: "accidents", labelKey: "reports.accidents" }
];

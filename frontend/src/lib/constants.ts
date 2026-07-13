export const VEHICLE_STATUS_LABELS: Record<number, string> = {
  0: "Active",
  1: "In Service",
  2: "Sold",
  3: "Out of Use"
};

export const VEHICLE_STATUSES = [
  { value: 0, label: "Active" },
  { value: 1, label: "In Service" },
  { value: 2, label: "Sold" },
  { value: 3, label: "Out of Use" }
];

export const RESERVATION_STATUS_LABELS: Record<number, string> = {
  0: "Pending",
  1: "Approved",
  2: "Rejected",
  3: "Cancelled"
};

export const RESERVATION_STATUSES = [
  { value: 0, label: "Pending" },
  { value: 1, label: "Approved" },
  { value: 2, label: "Rejected" },
  { value: 3, label: "Cancelled" }
];

export const FUEL_TYPES = ["Petrol", "Diesel", "Hybrid", "Electric", "LPG", "CNG", "Gas"];
export const SERVICE_TYPES = ["General Service", "Oil Change", "Tire Change/Control", "Part Change", "Maintenance", "Other"];
export const SERVICE_KM_INTERVALS = [5000, 10000, 15000];
export const DOCUMENT_TYPES = ["Registration", "Insurance", "Technical Control", "Ownership", "Other"];
export const RESERVATION_TYPES = ["Business Trip", "Personal Use", "Replacement Vehicle", "Maintenance", "Other"];
export const DRIVER_STATUSES = ["Active", "Suspended", "Left Company"];
export const INSPECTION_TYPES = ["Daily", "Weekly", "Before Trip", "After Trip", "Return Inspection"];
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
export const REPORTS = [
  { value: "fleet-summary", label: "Fleet Summary" },
  { value: "fuel-costs", label: "Fuel Costs" },
  { value: "service-costs", label: "Service Costs" },
  { value: "vehicle-costs", label: "Vehicle Costs" },
  { value: "reservations", label: "Reservations" },
  { value: "document-expiry", label: "Document Expiry" },
  { value: "work-orders", label: "Work Orders" }
];

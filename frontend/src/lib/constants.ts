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

export type Vehicle = {
  id: number;
  brand: string;
  model: string;
  fuel_type: string;
  vehicle_location: string;
  license_plate: string;
  year?: number | null;
  vin_number?: string | null;
  engine_cc?: number | null;
  odometer_km?: number | null;
  status: number;
  status_name: string;
};

export type UserRole = "admin" | "fleet_manager" | "mechanic" | "driver" | "finance" | "viewer";

export type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: CurrentUser;
};

export type VehiclePayload = Omit<Vehicle, "id" | "status_name">;

export type DriverStatus = "Active" | "Suspended" | "Left Company";

export type Driver = {
  id: number;
  full_name: string;
  phone_number?: string | null;
  email?: string | null;
  employee_number: string;
  department?: string | null;
  license_number: string;
  license_category: string;
  license_expiry_date: string;
  assigned_vehicle_id?: number | null;
  assigned_license_plate?: string | null;
  user_id?: number | null;
  status: DriverStatus;
  notes?: string | null;
  created_at: string;
  updated_at: string;
};

export type DriverPayload = Omit<Driver, "id" | "assigned_vehicle_id" | "created_at" | "updated_at"> & {
  assigned_vehicle_id?: number | null;
};

export type InspectionType = "Daily" | "Weekly" | "Before Trip" | "After Trip" | "Return Inspection";
export type InspectionItemStatus = "Pass" | "Fail" | "Not Checked";
export type InspectionOverallStatus = "Passed" | "Failed" | "Needs Review";

export type InspectionItem = {
  id?: number;
  item_name: string;
  status: InspectionItemStatus;
  comment?: string | null;
};

export type Inspection = {
  id: number;
  vehicle_id: number;
  license_plate: string;
  driver_id?: number | null;
  driver_name?: string | null;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status: InspectionOverallStatus;
  notes?: string | null;
  items: InspectionItem[];
  created_at: string;
  updated_at: string;
};

export type InspectionPayload = {
  vehicle_id?: number | null;
  license_plate?: string | null;
  driver_id?: number | null;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status?: InspectionOverallStatus | null;
  notes?: string | null;
  items: InspectionItem[];
};

export type DashboardSummary = {
  total_vehicles: number;
  status_summary: Array<{ status: number; count: number }>;
  location_summary: Array<{ location: string; count: number }>;
  reservation_status_summary: Array<{ status: string; count: number }>;
};

export type ServiceReminder = {
  license_plate: string;
  service_type: string;
  service_date: string;
  reminder_mode: string;
  next_service_date?: string | null;
  days_left?: number | null;
  current_odometer_km?: number | null;
  next_service_odometer_km?: number | null;
  next_service_km_interval?: number | null;
  km_left?: number | null;
};

export type VehicleServiceOverview = {
  id: number;
  license_plate: string;
  service_type: string;
  service_date: string;
  odometer_km?: number | null;
  workshop?: string | null;
  cost?: string | number | null;
  description?: string | null;
  bill_file_path?: string | null;
  next_service_date?: string | null;
  next_service_km_interval?: number | null;
  next_service_odometer_km?: number | null;
};

export type FuelRecord = {
  id: number;
  license_plate: string;
  brand: string;
  model: string;
  refuel_date: string;
  fuel_type: string;
  liters: string | number;
  cost_per_liter: string | number;
  total_cost: string | number;
  location: string;
  station_name: string;
  bill_file_path?: string | null;
  odometer_km: number;
};

export type VehiclePaper = {
  id: number;
  license_plate: string;
  vehicle_location: string;
  brand: string;
  model: string;
  document_type: string;
  issue_date: string;
  expiry_date: string;
  file_path: string;
};

export type Accident = {
  id: number;
  accident_date: string;
  location?: string | null;
  description?: string | null;
  license_plate?: string | null;
  brand?: string | null;
  model?: string | null;
  files: string[];
};

export type Reservation = {
  id: number;
  license_plate: string;
  reserved_by: string;
  reservation_type: string;
  start_date: string;
  end_date: string;
  notes?: string | null;
  status: number;
  status_name: string;
};


export type ApiMessage = {
  message?: string;
  id?: number;
};

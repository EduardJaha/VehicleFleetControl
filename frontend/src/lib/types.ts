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
  vehicle_name: string;
  driver_id?: number | null;
  driver_name?: string | null;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status: InspectionOverallStatus;
  notes?: string | null;
  items: InspectionItem[];
  failed_item_count: number;
  inspector?: string | null;
  archived: boolean;
  linked_work_order?: LinkedWorkOrder | null;
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
  inspector?: string | null;
  archived?: boolean;
  items: InspectionItem[];
};

export type WorkOrderStatus = "Open" | "Assigned" | "In Progress" | "Waiting for Parts" | "Completed" | "Cancelled";
export type WorkOrderPriority = "Low" | "Medium" | "High" | "Critical";
export type WorkOrderSource = "Manual" | "Inspection" | "Service Reminder" | "Breakdown" | "Other";
export type ServiceSource = "Manual" | "Work Order" | "Imported";
export type ReminderStatus = "Upcoming" | "Due Soon" | "Due" | "Overdue" | "Resolved" | "Dismissed";

export type LinkedWorkOrder = {
  id: number;
  title: string;
  status: WorkOrderStatus;
  priority: WorkOrderPriority;
};

export type LinkedService = {
  id: number;
  service_type: string;
  service_date: string;
  total_cost?: string | number | null;
};

export type LinkedInspection = {
  id: number;
  inspection_type: InspectionType;
  inspection_date: string;
  overall_status: InspectionOverallStatus;
};

export type LinkedServiceReminder = {
  id: number;
  service_type: string;
  due_date?: string | null;
  due_odometer_km?: number | null;
  status: ReminderStatus;
};

export type WorkOrder = {
  id: number;
  vehicle_id: number;
  license_plate: string;
  vehicle_name: string;
  driver_id?: number | null;
  driver_name?: string | null;
  inspection_id?: number | null;
  reminder_service_id?: number | null;
  source: WorkOrderSource;
  title: string;
  description?: string | null;
  reported_issue?: string | null;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  requested_by?: string | null;
  assigned_to?: string | null;
  workshop?: string | null;
  expected_completion_date?: string | null;
  actual_completion_date?: string | null;
  labor_cost?: string | number | null;
  parts_cost?: string | number | null;
  total_cost?: string | number | null;
  notes?: string | null;
  completed_odometer_km?: number | null;
  completion_notes?: string | null;
  completed_by?: string | null;
  created_by?: string | null;
  archived: boolean;
  source_inspection?: LinkedInspection | null;
  source_reminder?: LinkedServiceReminder | null;
  linked_service?: LinkedService | null;
  created_at: string;
  updated_at: string;
};

export type WorkOrderPayload = Omit<WorkOrder, "id" | "vehicle_id" | "vehicle_name" | "license_plate" | "driver_name" | "total_cost" | "created_at" | "updated_at"> & {
  vehicle_id?: number | null;
  license_plate?: string | null;
  labor_cost?: number | null;
  parts_cost?: number | null;
};

export type ReportValue = string | number | boolean | null;

export type ReportData = {
  kpis: Record<string, ReportValue>;
  rows: Array<Record<string, ReportValue>>;
};

export type DashboardSummary = {
  total_vehicles: number;
  status_summary: Array<{ status: number; count: number }>;
  location_summary: Array<{ location: string; count: number }>;
  reservation_status_summary: Array<{ status: string; count: number }>;
};

export type ServiceReminder = {
  id: number;
  vehicle_id: number;
  license_plate: string;
  vehicle_name: string;
  service_type: string;
  service_date: string;
  reminder_mode: string;
  next_service_date?: string | null;
  days_left?: number | null;
  current_odometer_km?: number | null;
  next_service_odometer_km?: number | null;
  next_service_km_interval?: number | null;
  km_left?: number | null;
  status: ReminderStatus;
  priority: WorkOrderPriority;
  linked_work_order?: LinkedWorkOrder | null;
};

export type VehicleServiceOverview = {
  id: number;
  vehicle_id: number;
  license_plate: string;
  vehicle_name: string;
  service_type: string;
  service_date: string;
  odometer_km?: number | null;
  workshop?: string | null;
  cost?: string | number | null;
  labor_cost?: string | number | null;
  parts_cost?: string | number | null;
  total_cost?: string | number | null;
  description?: string | null;
  bill_file_path?: string | null;
  next_service_date?: string | null;
  next_service_km_interval?: number | null;
  next_service_odometer_km?: number | null;
  source: ServiceSource;
  status: "Completed" | "Archived";
  archived: boolean;
  linked_work_order?: LinkedWorkOrder | null;
  reminder_status?: ReminderStatus | null;
};

export type ServiceAttachment = {
  id: number;
  file_path: string;
  uploaded_at: string;
  attachment_type: string;
};

export type VehicleServiceDetail = VehicleServiceOverview & {
  bills: ServiceAttachment[];
};

export type PageResult<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

export type MaintenanceRecordSummary = {
  id: number;
  record_type: string;
  vehicle_id: number;
  vehicle: string;
  license_plate: string;
  title: string;
  status: string;
  priority?: string | null;
  date?: string | null;
  due_date?: string | null;
  assigned_to?: string | null;
  cost?: string | number | null;
  href: string;
  description?: string | null;
};

export type MaintenanceSummary = {
  work_orders_by_status: Record<string, number>;
  work_orders_by_priority: Record<string, number>;
  open_work_orders: number;
  assigned_work_orders: number;
  in_progress_work_orders: number;
  waiting_for_parts_work_orders: number;
  critical_work_orders_count: number;
  overdue_work_orders_count: number;
  completed_work_orders_this_month: number;
  services_completed_this_month: number;
  upcoming_reminders_count: number;
  overdue_reminders_count: number;
  failed_inspections_count: number;
  inspections_needing_review_count: number;
  vehicles_in_service_count: number;
  monthly_maintenance_cost: string | number;
  critical_work_orders: MaintenanceRecordSummary[];
  overdue_work_orders: MaintenanceRecordSummary[];
  overdue_service_reminders: MaintenanceRecordSummary[];
  failed_inspections: MaintenanceRecordSummary[];
  vehicles_in_service: MaintenanceRecordSummary[];
  recently_created_work_orders: MaintenanceRecordSummary[];
  recently_completed_work_orders: MaintenanceRecordSummary[];
  recent_services: MaintenanceRecordSummary[];
  recent_inspections: MaintenanceRecordSummary[];
};

export type VehicleMaintenanceSummary = {
  vehicle_id: number;
  license_plate: string;
  open_work_orders: number;
  critical_work_orders: number;
  last_service?: LinkedService | null;
  next_service?: LinkedServiceReminder | null;
  overdue_reminders: number;
  failed_inspections: number;
  maintenance_cost_this_month: string | number;
  maintenance_cost_this_year: string | number;
  lifetime_maintenance_cost: string | number;
};

export type MaintenanceTimelineEvent = {
  id: string;
  occurred_at: string;
  event_type: string;
  title: string;
  description?: string | null;
  status?: string | null;
  priority?: string | null;
  actor?: string | null;
  related_record_type: string;
  related_record_id: number;
  href: string;
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

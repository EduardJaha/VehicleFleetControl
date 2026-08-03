export type RegistrationCountryCode = "AL" | "XK";

export interface RegistrationCountryRegion {
  code: string;
  name: string;
}

export interface RegistrationCountryOption {
  code: RegistrationCountryCode;
  name: string;
  placeholder: string;
  example: string;
  description: string;
  helper_text: string[];
  regions?: RegistrationCountryRegion[];
}

export type Vehicle = {
  id: number;
  brand_id: number | null;
  model_id: number | null;
  brand: string;
  model: string;
  fuel_type: string;
  vehicle_location: string;
  vehicle_category?: string | null;
  registration_country: RegistrationCountryCode | null;
  registration_country_name: string | null;
  license_plate: string;
  year?: number | null;
  vin_number?: string | null;
  engine_cc?: number | null;
  odometer_km?: number | null;
  status: number;
  status_name: string;
  archived?: boolean;
  archived_at?: string | null;
  archived_by?: number | null;
};

export interface VehicleBrand {
  id: number;
  name: string;
  is_active: boolean;
}

export interface VehicleModel {
  id: number;
  brand_id: number;
  name: string;
  is_active: boolean;
}

export type UserRole = "admin" | "fleet_manager" | "mechanic" | "driver" | "finance" | "viewer";

export type CurrentUser = {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  preferred_language: "en" | "sq";
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: CurrentUser;
};

export type VehiclePayload = Omit<Vehicle, "id" | "status_name" | "registration_country_name" | "brand" | "model" | "brand_id" | "model_id"> & {
  brand_id: number;
  model_id: number;
  registration_country: RegistrationCountryCode;
};

export type VehicleFormValues = Omit<VehiclePayload, "brand_id" | "model_id" | "registration_country"> & {
  brand_id: number | null;
  model_id: number | null;
  registration_country: RegistrationCountryCode | null;
};

export type VehicleFormInitialValues = VehicleFormValues & {
  brand_name?: string;
  model_name?: string;
};

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
  archived?: boolean;
  archived_at?: string | null;
  archived_by?: number | null;
};

export type DriverPayload = Omit<Driver, "id" | "assigned_vehicle_id" | "created_at" | "updated_at"> & {
  assigned_vehicle_id?: number | null;
};

export type ImportEntityType =
  | "Vehicles" | "Drivers" | "Historical Services" | "Fuel and Charging Records"
  | "Documents Metadata" | "Vehicle Assignments" | "Vendors" | "Parts";
export type ImportUpdateMode = "create_only" | "update_existing";
export type ImportTransactionMode = "row" | "file";
export type ImportJobStatus = "Uploaded" | "Validating" | "Ready" | "Importing" | "Completed" | "Completed With Errors" | "Failed" | "Cancelled";

export type ImportFieldDefinition = {
  key: string;
  label: string;
  required: boolean;
  example?: string | number | null;
};

export type ImportRowResult = {
  id: number;
  row_number: number;
  status: string;
  action: string;
  raw_data: Record<string, unknown>;
  mapped_data?: Record<string, unknown> | null;
  errors: Array<{ field?: string; code?: string; message?: string }>;
  duplicate_fields: string[];
  target_id?: number | null;
};

export type ImportJob = {
  id: number;
  entity_type: ImportEntityType;
  filename: string;
  uploaded_by: number;
  status: ImportJobStatus;
  column_mapping?: Record<string, string> | null;
  update_mode?: ImportUpdateMode | null;
  transaction_mode?: ImportTransactionMode | null;
  source_headers: string[];
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  created_rows: number;
  updated_rows: number;
  skipped_rows: number;
  started_at?: string | null;
  completed_at?: string | null;
  error_report_path?: string | null;
  created_at: string;
  rows: ImportRowResult[];
};

export type ImportUpload = {
  id: number;
  entity_type: ImportEntityType;
  filename: string;
  status: ImportJobStatus;
  headers: string[];
  fields: ImportFieldDefinition[];
  suggested_mapping: Record<string, string>;
};

export type VehicleAssignmentStatus = "Scheduled" | "Active" | "Completed" | "Cancelled" | "Overdue";

export type VehicleAssignment = {
  id: number;
  vehicle_id: number;
  driver_id: number;
  reservation_id?: number | null;
  vehicle_license_plate: string;
  vehicle_name: string;
  driver_name: string;
  assigned_by_user_id?: number | null;
  assigned_by_name?: string | null;
  ended_by_user_id?: number | null;
  ended_by_name?: string | null;
  start_datetime: string;
  end_datetime?: string | null;
  start_odometer_km: number;
  end_odometer_km?: number | null;
  start_energy_level?: number | null;
  end_energy_level?: number | null;
  purpose?: string | null;
  destination?: string | null;
  documents_handed_over: string[];
  notes?: string | null;
  return_notes?: string | null;
  status: VehicleAssignmentStatus;
  created_at: string;
  updated_at: string;
  archived: boolean;
  archived_at?: string | null;
  archived_by?: number | null;
  conditions: VehicleConditionRecord[];
};

export type VehicleAssignmentPayload = {
  vehicle_id: number;
  driver_id: number;
  reservation_id?: number | null;
  start_datetime: string;
  start_odometer_km: number;
  start_energy_level?: number | null;
  purpose?: string | null;
  destination?: string | null;
  documents_handed_over?: string[];
  notes?: string | null;
};

export type VehicleAssignmentStartPayload = {
  start_datetime?: string | null;
  start_odometer_km?: number | null;
  start_energy_level?: number | null;
  notes?: string | null;
};

export type VehicleAssignmentCompletePayload = {
  end_datetime: string;
  end_odometer_km: number;
  end_energy_level?: number | null;
  return_notes?: string | null;
};

export type VehicleConditionType = "Checkout" | "Return";

export type VehicleConditionRecord = {
  id: number;
  vehicle_assignment_id: number;
  vehicle_id: number;
  driver_id: number;
  record_type: VehicleConditionType;
  recorded_at: string;
  odometer_km: number;
  energy_level?: number | null;
  vehicle_condition: string;
  damage_description?: string | null;
  driver_comments?: string | null;
  return_inspection_required: boolean;
  attachment_count: number;
};

export type VehicleCheckoutPayload = {
  assignment_id?: number | null;
  vehicle_id: number;
  driver_id: number;
  reservation_id?: number | null;
  checkout_datetime: string;
  starting_odometer_km: number;
  energy_level?: number | null;
  vehicle_condition: string;
  existing_damage?: string | null;
  documents_handed_over: string[];
  purpose?: string | null;
  destination?: string | null;
  notes?: string | null;
};

export type VehicleReturnPayload = {
  return_datetime: string;
  ending_odometer_km: number;
  energy_level?: number | null;
  vehicle_condition: string;
  new_damage?: string | null;
  driver_comments?: string | null;
  return_inspection_required: boolean;
  create_accident: boolean;
  create_work_order: boolean;
};

export type VehicleCheckoutResult = {
  assignment: VehicleAssignment;
  condition_record: VehicleConditionRecord;
};

export type VehicleReturnResult = {
  assignment: VehicleAssignment;
  condition_record: VehicleConditionRecord;
  inspection_id?: number | null;
  accident_id?: number | null;
  work_order_id?: number | null;
};

export type InspectionType =
  | "General"
  | "Daily"
  | "Weekly"
  | "Monthly"
  | "Before Trip"
  | "After Trip"
  | "Random"
  | "Return Inspection";
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
  vehicle_assignment_id?: number | null;
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

export type WorkOrderCompletionPayload = {
  actual_completion_date: string;
  completed_odometer_km: number;
  workshop?: string | null;
  labor_cost: number;
  parts_cost: number;
  completion_notes?: string | null;
  create_service_record: boolean;
  service_type?: string | null;
  service_description?: string | null;
  next_service_km_interval?: number | null;
  next_service_date?: string | null;
  resolve_source_reminder: boolean;
};

export type WorkOrderCompletionResult = {
  work_order: WorkOrder;
  service?: LinkedService | null;
  reminder_resolved: boolean;
  next_reminder_created: boolean;
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
  active_usage: DashboardActiveUsage[];
  active_usage_count: number;
  overdue_return_count: number;
};

export type DashboardActiveUsage = {
  assignment_id: number;
  vehicle_id: number;
  driver_id: number;
  license_plate: string;
  vehicle_name: string;
  driver_name: string;
  checkout_datetime: string;
  expected_return_datetime?: string | null;
  destination?: string | null;
  overdue: boolean;
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
  event_code?: string | null;
  title_key?: string | null;
  description_key?: string | null;
  params?: Record<string, unknown> | null;
};

export type EnergyUnit = "L" | "KWH";

export type FuelRecord = {
  id: number;
  vehicle_id: number;
  vehicle_assignment_id?: number | null;
  license_plate: string;
  brand: string;
  model: string;
  refuel_date: string;
  fuel_type: string;
  quantity: string | number;
  unit: EnergyUnit;
  unit_cost: string | number;
  total_cost: string | number;
  location: string;
  station_name: string;
  bill_file_path?: string | null;
  odometer_km: number;
  archived?: boolean;
  unit_review_required?: boolean;
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
  archived?: boolean;
};

export type DocumentComplianceStatus =
  | "Missing" | "Valid" | "Expiring Soon" | "Expired"
  | "Renewal In Progress" | "Rejected" | "Archived";

export type DocumentRequirement = {
  id: number;
  document_type: string;
  applies_to_vehicle_category?: string | null;
  applies_to_country?: string | null;
  applies_to_driver: boolean;
  required: boolean;
  validity_months?: number | null;
  warning_days: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type DocumentVersion = {
  id: number;
  document_id: number;
  version_number: number;
  file_path: string;
  document_number?: string | null;
  issuing_authority?: string | null;
  issue_date: string;
  expiry_date: string;
  uploaded_by?: number | null;
  uploaded_at: string;
  verified_by?: number | null;
  verified_at?: string | null;
  rejection_reason?: string | null;
  renewal_status: "None" | "In Progress" | "Submitted" | "Approved" | "Rejected";
  is_current: boolean;
  archived: boolean;
};

export type ComplianceItem = {
  requirement_id: number;
  document_id?: number | null;
  version_id?: number | null;
  document_type: string;
  owner_type: "Vehicle" | "Driver";
  owner_id: number;
  owner_name: string;
  department?: string | null;
  location?: string | null;
  country?: string | null;
  status: DocumentComplianceStatus;
  issue_date?: string | null;
  expiry_date?: string | null;
  warning_days: number;
  file_path?: string | null;
};

export type ComplianceRate = {
  name: string;
  compliant: number;
  required: number;
  rate: number;
};

export type DocumentComplianceDashboard = {
  missing_required: ComplianceItem[];
  expired: ComplianceItem[];
  expiring_in_7_days: ComplianceItem[];
  expiring_in_30_days: ComplianceItem[];
  renewal_in_progress: ComplianceItem[];
  items: ComplianceItem[];
  compliance_by_vehicle: ComplianceRate[];
  compliance_by_driver: ComplianceRate[];
  compliance_by_department: ComplianceRate[];
  compliance_by_location: ComplianceRate[];
  overall_compliance_rate: number;
};

export type Accident = {
  id: number;
  vehicle_id?: number | null;
  driver_id?: number | null;
  vehicle_assignment_id?: number | null;
  reservation_id?: number | null;
  accident_date: string;
  accident_datetime?: string | null;
  location?: string | null;
  severity?: "Minor" | "Moderate" | "Severe" | "Critical";
  status?: "Reported" | "Under Review" | "Claim Opened" | "Repair Approved" | "Repair In Progress" | "Resolved" | "Closed" | "Rejected";
  police_involved?: boolean;
  police_report_number?: string | null;
  description?: string | null;
  vehicle_available_after_accident?: boolean;
  estimated_damage_cost?: number | string | null;
  actual_damage_cost?: number | string | null;
  fault_determination?: string | null;
  license_plate?: string | null;
  brand?: string | null;
  model?: string | null;
  driver_name?: string | null;
  files: string[];
  archived?: boolean;
};

export type AccidentClaim = {
  id: number;
  insurance_company: string;
  policy_number: string;
  claim_number: string;
  claim_status: string;
  claim_opened_date: string;
  claim_closed_date?: string | null;
  settlement_amount?: string | null;
  deductible?: string | null;
  adjuster_name?: string | null;
  notes?: string | null;
  insurance_document_id?: number | null;
  insurance_document_type?: string | null;
};

export type AccidentDetail = Accident & {
  assignment_id?: number | null;
  claim?: AccidentClaim | null;
  parties: Array<Record<string, unknown>>;
  injuries: Array<Record<string, unknown>>;
  work_orders: Array<{
    id: number; title: string; status: string; total_cost?: string | null;
    service?: { id: number; service_type: string; service_date: string; cost?: string | null } | null;
  }>;
  attachments: Array<Attachment & { download_url: string }>;
  timeline: Array<{ id: number; action: string; description?: string | null; username?: string | null; created_at: string }>;
  resolved_at?: string | null;
  closed_at?: string | null;
};

export type Reservation = {
  id: number;
  vehicle_id: number;
  vehicle_assignment_id?: number | null;
  license_plate: string;
  reserved_by: string;
  reservation_type: string;
  start_date: string;
  end_date: string;
  notes?: string | null;
  status: number;
  status_name: string;
  archived?: boolean;
};


export type ApiMessage = {
  message?: string;
  id?: number;
};

export type NotificationStatus = "Unread" | "Read" | "Resolved" | "Dismissed";
export type NotificationPriority = "Low" | "Medium" | "High" | "Critical";

export type Notification = {
  id: number;
  notification_type: string;
  title: string;
  message: string;
  title_key?: string | null;
  message_key?: string | null;
  message_params?: Record<string, unknown> | null;
  priority: NotificationPriority;
  status: NotificationStatus;
  entity_type?: string | null;
  entity_id?: number | null;
  created_at: string;
  read_at?: string | null;
  resolved_at?: string | null;
  dismissed_at?: string | null;
};

export type AuditLog = {
  id: number;
  user_id?: number | null;
  username?: string | null;
  action: string;
  entity_type: string;
  entity_id?: number | null;
  old_values?: Record<string, unknown> | null;
  new_values?: Record<string, unknown> | null;
  description?: string | null;
  action_code?: string | null;
  description_key?: string | null;
  description_params?: Record<string, unknown> | null;
  ip_address?: string | null;
  created_at: string;
};

export type Attachment = {
  id: number;
  original_filename: string;
  mime_type: string;
  file_size: number;
  entity_type: string;
  entity_id: number;
  uploaded_at: string;
};

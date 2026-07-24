export type Organization = {
  id: string;
  name: string;
  slug: string;
  legal_name: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  address: string;
  billing_address: string;
};

export type Site = {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  timezone: string;
  address: string;
};

export type Membership = {
  id: string;
  organization_id: string;
  site_id: string | null;
  role: UserRole;
  organizations?: Organization | Organization[] | null;
  sites?: Site | Site[] | null;
};

export type CurrentMembershipRow = {
  membership_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  organization_legal_name?: string;
  organization_contact_name?: string;
  organization_contact_email?: string;
  organization_contact_phone?: string;
  organization_address?: string;
  organization_billing_address?: string;
  site_id: string | null;
  site_name: string | null;
  site_slug: string | null;
  site_timezone: string | null;
  site_address?: string | null;
  role: UserRole;
};

export type UserRole = "system_admin" | "owner" | "admin" | "org_admin" | "site_admin" | "viewer" | "site_operator";

export type Device = {
  id: string;
  organization_id: string;
  site_id: string;
  serial_number: string;
  display_name: string;
  status: "unprovisioned" | "online" | "offline" | "recording" | "error" | "disabled";
  provisioned_at: string | null;
  last_heartbeat_at: string | null;
  software_version: string;
  last_update_id: string;
  metadata: Record<string, unknown>;
  scanner_schedule_enabled: boolean;
  scanner_active_start: string;
  scanner_active_end: string;
  scanner_active_days: number[];
  created_at: string;
  updated_at: string;
};

export type Video = {
  id: string;
  organization_id: string;
  site_id: string;
  device_id: string | null;
  scanned_id: string;
  device_serial_number: string;
  device_display_name: string;
  filename: string;
  storage_bucket: string;
  storage_path: string;
  status: "pending_upload" | "uploading" | "uploaded" | "failed" | "deleted";
  is_hidden: boolean;
  hidden_reason: string;
  hidden_at: string | null;
  hidden_by: string | null;
  deletion_reason: string;
  deleted_at: string | null;
  deleted_by: string | null;
  privacy_status: "not_processed" | "processed" | "failed" | "not_required";
  privacy_mode?: "not_required" | "local_pi" | "cloud_worker" | "manual";
  raw_storage_bucket?: string;
  raw_storage_path?: string;
  processed_storage_bucket?: string;
  processed_storage_path?: string;
  privacy_processed_at?: string | null;
  privacy_error?: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  size_bytes: number | null;
  created_at: string;
  devices?: Pick<Device, "serial_number" | "display_name"> | Pick<Device, "serial_number" | "display_name">[] | null;
  sites?: Pick<Site, "name"> | Pick<Site, "name">[] | null;
};

export type DeviceEvent = {
  id: string;
  organization_id: string;
  site_id: string;
  device_id: string;
  event_type: string;
  severity: "debug" | "info" | "warning" | "error" | "critical";
  message: string;
  created_at: string;
  devices?: Pick<Device, "serial_number" | "display_name"> | Pick<Device, "serial_number" | "display_name">[] | null;
};

export type SoftwareRollout = {
  id: string;
  update_id: string;
  policy: "force" | "night";
  target_ref: string;
  target_commit: string;
  version: string;
  description: string;
  enabled: boolean;
  created_at: string;
};

export type BillingPrice = {
  id: string;
  code: string;
  name: string;
  description: string;
  component: "hardware_setup" | "site_service" | "device_license" | "storage_addon";
  billing_period: "one_time" | "monthly";
  currency: string;
  unit_amount_minor: number;
  unit_label: string;
  included_quantity: number | null;
  taxable: boolean;
  active: boolean;
  sort_order: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type SiteBillingUsage = {
  organization_id: string;
  site_id: string;
  site_name: string;
  included_storage_gb: number;
  extra_storage_gb: number;
  total_storage_gb: number;
  used_storage_bytes: number;
  used_storage_gb: number;
  usage_pct: number;
  uploaded_video_count: number;
  shared_video_count: number;
  protected_video_count: number;
  active_device_count: number;
  billable_device_count: number;
  hardware_pending_count: number;
  auto_delete_enabled: boolean;
  protect_shared_videos: boolean;
  retention_days: number;
  warning_threshold_pct: number;
  critical_threshold_pct: number;
};

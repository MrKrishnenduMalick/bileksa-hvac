export type CallRow = {
  id: string;
  reference: string;
  caller: string | null;
  caller_name: string | null;
  started_at: string | null;
  status: string;
  routing: string;
  summary: string | null;
  duration_seconds: number | null;
  outcome: string;
  urgent: boolean;
  emergency_type: string | null;
  transfer_status: string;
  lead_id: string | null;
  lead_created: boolean;
  callback_requested: boolean;
  appointment_requested: boolean;
  numbers_to_check: string[];
};

export type Lead = {
  id: string;
  customer_name: string | null;
  callback_number: string | null;
  number_confirmed: boolean;
  address: string | null;
  zip_code: string | null;
  issue_summary: string | null;
  service_type: string | null;
  urgency: string;
  status: string;
  source: string;
  callback_status: string;
  callback_preferred_time: string | null;
  callback_reason: string | null;
  equipment_type: string | null;
  customer_type: string | null;
  notes: string | null;
  appointment_status: string;
  preferred_appointment: string | null;
  created_at: string;
  updated_at: string;
};

export type Receptionist = {
  assistant_name: string;
  provisioning_state: string;
  status_label: string;
  live: boolean;
  service_status: string;
  phone_state: string;
  last_config_update_at: string | null;
};

export type Overview = {
  period_start: string;
  period_end: string;
  receptionist: Receptionist;
  metrics: Record<string, number>;
  usage: Usage;
  recent_activity: CallRow[];
};

export type Usage = {
  service_status: string;
  package: { id: string; code: string; name: string } | null;
  included_minutes: number;
  used_minutes: number;
  remaining_minutes: number;
  usage_percent: number;
  limit_reached: boolean;
  period_start: string | null;
  reset_date: string | null;
  renewal_overdue: boolean;
};

export type Package = {
  id: string;
  code?: string;
  name: string;
  price_cents: number;
  included_minutes: number;
  features: string[];
  active?: boolean;
  sort_order?: number;
};

export type UpgradeRequest = {
  id: string;
  business_id?: string;
  business_name?: string | null;
  requested_package_id?: string | null;
  requested_package?: Package | null;
  message: string | null;
  status: string;
  admin_notes?: string | null;
  created_at: string;
  resolved_at: string | null;
};

export type Notification = {
  id: string;
  business_id: string | null;
  kind: string;
  title: string;
  body: string;
  email_status: string;
  read: boolean;
  created_at: string;
};

export type EmergencyRule = {
  key: string;
  label: string;
  builtin?: boolean;
  transfer: boolean;
  instructions: string;
};

export type Faq = {
  id: string;
  category: string;
  question: string;
  answer: string;
  active: boolean;
};

export type Service = {
  id: string;
  name: string;
  description: string | null;
  price_min_cents: number | null;
  price_max_cents: number | null;
  price_note: string | null;
  available: boolean;
};

export type PhoneLine = {
  business_number: string;
  carrier: string | null;
  destination_number: string | null;
  phone_provider?: "vapi" | "twilio";
  forwarding_mode: string;
  state: string;
  test_window_until: string | null;
  verified_at: string | null;
  last_error: string | null;
  routing_synced: boolean;
  synced_at: string | null;
  steps: string[];
} | null;

export const LEAD_STATUSES = [
  "new",
  "contacted",
  "in_progress",
  "converted",
  "closed",
  "unqualified",
];

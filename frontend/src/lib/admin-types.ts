import type { Business } from "./api";
import type { CallRow, PhoneLine, Usage } from "./types";

export type ClientRow = Usage & {
  id: string;
  name: string;
  created_at: string;
  approaching_limit: boolean;
  assistant_state: string | null;
  assistant_error: string | null;
  phone_state: string;
  open_upgrade_requests: number;
};

export type ClientDetail = {
  business: Business & { transfer_mode: string; unavailable_message: string | null };
  usage: Usage;
  assistant: {
    vapi_assistant_id: string | null;
    state: string | null;
    last_error: string | null;
    template_version: number | null;
    current_template_version: number;
    verified_at: string | null;
  };
  phone: PhoneLine;
  members: { user_id: string; role: string; created_at: string }[];
  readiness: { step: string; done: boolean }[];
  recent_calls: CallRow[];
};

export type Payment = {
  id: string;
  amount_cents: number;
  payment_type: string;
  paid_on: string;
  status: string;
  period_start: string | null;
  period_end: string | null;
  notes: string | null;
  recorded_by: string;
  created_at: string;
};

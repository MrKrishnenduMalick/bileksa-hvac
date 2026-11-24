"""Application settings. Every secret comes from the environment; nothing is stored in code."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"  # development | staging | production | test
    database_url: str = "postgresql+asyncpg://bileksa:bileksa@localhost:5432/bileksa_dev"
    public_api_url: str = "http://localhost:8000"  # URL Vapi uses to reach this backend
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"

    # Supabase Auth. HS256 secret (legacy) OR the project URL for JWKS (asymmetric keys).
    supabase_url: str = ""
    supabase_jwt_secret: str = ""
    supabase_jwt_audience: str = "authenticated"
    # Public (publishable) anon key: used server-side only for admin password re-verification.
    supabase_anon_key: str = ""
    # Backend-only secret: used to invite client owners (Supabase Admin API). Never sent to
    # the frontend.
    supabase_service_role_key: str = ""

    # Vapi
    vapi_api_url: str = "https://api.vapi.ai"
    vapi_private_key: str = ""
    vapi_webhook_secret: str = ""  # value Vapi sends via its Custom Credential (Bearer)
    vapi_credential_id: str = ""  # Vapi Custom Credential id attached to tools/assistants
    vapi_tool_ids: str = ""  # comma-separated ids created by `python -m app.cli setup-vapi-tools`
    vapi_request_timeout_s: float = 30.0
    vapi_phone_area_code: str = "713"
    # Confirm each new call ID with Vapi's Call API before binding it (one request per call)
    verify_calls_with_vapi: bool = True

    # Master template choices (decision D9 is made by listening tests; these are defaults)
    voice_provider: str = "11labs"
    voice_id: str = "sarah"
    model_provider: str = "openai"
    model_name: str = "gpt-4.1"
    transcriber_provider: str = "deepgram"
    transcriber_model: str = "nova-3"
    # Optional voice-pipeline tuning. All OFF/empty by default: nothing is sent to Vapi and its
    # own defaults apply, exactly as before. Values are read as text and validated when the
    # assistant is built; an invalid value is ignored (logged), never sent, so it can't break
    # calls or app start-up. See docs/live-call-tests.md before enabling any of them.
    speech_wait_seconds: str = ""  # startSpeakingPlan.waitSeconds, 0-2
    speech_smart_endpointing: str = (
        ""  # startSpeakingPlan.smartEndpointingPlan.provider: vapi|livekit
    )
    speech_stop_num_words: str = ""  # stopSpeakingPlan.numWords, 0-5
    speech_stop_backoff_seconds: str = ""  # stopSpeakingPlan.backoffSeconds, 0-10
    silence_timeout_seconds: str = ""  # silenceTimeoutSeconds, 10-3600
    transcriber_keyterms: str = ""  # "true": Deepgram Nova-3 keyterm boosting (HVAC words, name)
    transcriber_smart_format: str = ""  # "true": Deepgram smartFormat (numbers, dates)

    # Provisioning timing (section 3 of the plan)
    provisioning_lease_s: int = 300
    provisioning_min_lease_left_s: int = 60
    provisioning_settle_s: int = 600
    provisioning_duplicate_window_s: int = 86400
    provisioning_max_attempts: int = 3

    # Internal sweep (called by Supabase pg_cron)
    internal_sweep_secret: str = ""
    run_sweep_on_startup: bool = True

    # Notifications (email is optional; notifications always appear in the dashboards)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    admin_notification_email: str = ""  # default; admins can override in platform settings

    # Twilio (optional): import a client's Twilio number into Vapi instead of a Vapi number
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

    # Public demo deployment (separate database; never enable on the client deployment)
    demo_mode: bool = False
    demo_owner_email: str = "owner@houstoncomfort.example"
    demo_owner_password: str = ""
    demo_admin_email: str = "admin@bileksa-demo.example"
    demo_admin_password: str = ""
    # Vapi PUBLIC key for browser calls. Restrict it in the Vapi dashboard to the demo origin
    # and the demo assistant. Never put the private key here.
    vapi_public_key: str = ""
    demo_voice_max_call_seconds: int = 180
    demo_voice_max_calls_per_day: int = 25
    demo_voice_calls_per_ip_per_hour: int = 3
    demo_max_clients: int = 12
    # Hard limits only the operator can change (env), because the demo admin sign-in is public:
    # the admin screen can lower the monthly voice budget but never raise it above this ceiling,
    # and DEMO_LIVE_VOICE=false switches live voice off whatever the admin screen says.
    demo_voice_budget_cap_usd: float = 5.0
    demo_live_voice: bool = True

    # Lead de-duplication: a repeat call from the same number reuses the open lead
    lead_dedupe_hours: int = 12

    # BILEKSA admins must sign in with multi-factor authentication (Supabase aal2)
    require_admin_mfa: bool = True

    # Rate limits (requests per minute)
    rate_limit_dashboard: int = 300
    rate_limit_vapi: int = 600
    rate_limit_reauth: int = 5
    rate_limit_public: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def tool_id_list(self) -> list[str]:
        return [t.strip() for t in self.vapi_tool_ids.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

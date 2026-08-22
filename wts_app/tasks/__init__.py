# Import task modules so Celery autodiscover registers @shared_task handlers.
from .debug import ping  # noqa: F401
from .gazette import update_gazette_notices  # noqa: F401
from .bills import update_bill, update  # noqa: F401
from .monitored_sources import poll_monitored_sources, process_system_event_task  # noqa: F401
from .gemini import process_completed_gemini_batches  # noqa: F401
from .workbooks import close_completed_workbook  # noqa: F401
from .hansard import get_daily, get_results  # noqa: F401
from .auto_updates import clean_up_auto_updates, daily_email_summary  # noqa: F401
from .feedback import notify_staff_feedback_submitted  # noqa: F401
from .site_search import *
from .firebase import (  # noqa: F401
    push_event as push_event_to_firebase,
    push_persistent as push_persistent_to_firebase,
    publish_manifest as publish_election_manifest,
    sync_live_version as sync_live_election_version,
)

# Import task modules so Celery autodiscover registers @shared_task handlers.
from .debug import ping  # noqa: F401
from .gazette import update_gazette_notices  # noqa: F401
from .bills import update_bill  # noqa: F401
from celery import shared_task

from wts_app.ingestion.preprocess import process_system_event
from wts_app.ingestion.sources.base import DetectedItem
from wts_app.ingestion.sources.registry import get_source_handler
from wts_app.models import MonitoredSource, SystemEvent


@shared_task
def poll_monitored_sources():
    for source in MonitoredSource.objects.filter(is_active=True):
        handler = get_source_handler(source.handler)
        for item in handler.poll(source):
            event, created = SystemEvent.objects.get_or_create(
                source=source,
                external_id=item.external_id,
                defaults={
                    "payload": {
                        **item.payload,
                        "source_url": item.source_url,
                    },
                    "status": SystemEvent.Status.PENDING,
                },
            )
            if created:
                process_system_event_task.delay(str(event.id))


@shared_task
def process_system_event_task(event_id: str):
    process_system_event(event_id)

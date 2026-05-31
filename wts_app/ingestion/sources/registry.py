from .gazette import GazetteElectoralActHandler

SOURCE_HANDLER_REGISTRY = {
    GazetteElectoralActHandler.slug: GazetteElectoralActHandler(),
}


def get_source_handler(handler_key: str):
    try:
        return SOURCE_HANDLER_REGISTRY[handler_key]
    except KeyError as exc:
        raise ValueError(f"Unknown source handler '{handler_key}'.") from exc

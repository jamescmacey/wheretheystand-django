from authlib.integrations.django_client import OAuth
import os

from dotenv import load_dotenv
load_dotenv()

# Initialize OpenTelemetry exporter before DjangoInstrumentor
# This ensures the TracerProvider is set up before DjangoInstrumentor instruments Django
try:
    from wts_app.exporter import tracer  # noqa: F401
except ImportError:
    pass  # exporter might not be available in all contexts

oauth = OAuth()
oauth.register(
    'cloudflare',
    client_id=os.getenv('OIDC_CLIENT_ID'),
    client_secret=os.getenv('OIDC_CLIENT_SECRET'),
    server_metadata_url=os.getenv('OIDC_CONFIGURATION'),
    client_kwargs={'scope': 'openid email'},
)
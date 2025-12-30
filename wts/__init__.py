from authlib.integrations.django_client import OAuth
import os

from dotenv import load_dotenv
load_dotenv()

oauth = OAuth()
oauth.register(
    'cloudflare',
    client_id=os.getenv('OIDC_CLIENT_ID'),
    client_secret=os.getenv('OIDC_CLIENT_SECRET'),
    server_metadata_url=os.getenv('OIDC_CONFIGURATION'),
    client_kwargs={'scope': 'openid email'},
)
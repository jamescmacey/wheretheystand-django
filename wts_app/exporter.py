# exporter.py

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
import os

# Define the service name resource
resource = Resource(attributes={
    SERVICE_NAME: "wts-app"  # Replace with your actual service name
})

# Create a TracerProvider with the defined resource
provider = TracerProvider(resource=resource)

# Configure the OTLP/HTTP Span Exporter with necessary headers and endpoint
otlp_exporter = OTLPSpanExporter(
    endpoint="https://us-east-1.aws.edge.axiom.co/v1/traces",
    headers={
        "Authorization": "Bearer " + os.getenv("AXIOM_API_TOKEN"),  # Replace with your actual API token
        "X-Axiom-Dataset": os.getenv("AXIOM_DATASET")    # Replace with your dataset name
    }
)

# Create a BatchSpanProcessor with the OTLP exporter
processor = BatchSpanProcessor(otlp_exporter)
provider.add_span_processor(processor)

# Set the TracerProvider as the global tracer provider
trace.set_tracer_provider(provider)

# Define a tracer for external use
tracer = trace.get_tracer("wts-app")
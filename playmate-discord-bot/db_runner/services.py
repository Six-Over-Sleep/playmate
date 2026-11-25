"""Reuse existing lazy service builders; each thread/process owns its instance."""
from importlib import import_module


def build_service(feature):
    return import_module(f"{feature}_share.db_lambda").build_service()


def close_service(service):
    service.repo._db.close()


def sqs_client(settings):
    # EC2 instance profile only: do not silently use a developer profile or access keys.
    import boto3
    import botocore.session
    from botocore.config import Config
    session = botocore.session.get_session()
    resolver = session.get_component("credential_provider")
    resolver.providers = [p for p in resolver.providers if p.METHOD == "iam-role"]
    return boto3.Session(botocore_session=session).client(
        "sqs", region_name=settings.region,
        config=Config(connect_timeout=5, read_timeout=settings.read_timeout,
                      retries={"mode": "standard", "total_max_attempts": 2}))


def configure_publisher(service, client):
    # DM wrapper remains intact; send and verify still receive its FIFO attributes.
    from dm_share.fifo import DmFifoPublisher
    publisher = service.publisher
    if isinstance(publisher, DmFifoPublisher):
        publisher = publisher.inner
    publisher._client = client

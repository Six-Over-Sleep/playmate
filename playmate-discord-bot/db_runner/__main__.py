import argparse
import logging
import threading

from career_share.settings import SettingsError
from db_runner.settings import load_settings
from db_runner.services import build_service, close_service, configure_publisher, sqs_client
from db_runner.runtime import ProcessLock, install_signals
from db_runner.scheduler import Scheduler
from db_runner.results import ResultConsumer

log = logging.getLogger("db_runner")


def cleanup(service=None, client=None):
    for close in ((lambda: close_service(service)) if service is not None else None,
                  client.close if client is not None else None):
        if close is not None:
            try:
                close()
            except Exception as error:
                log.error("resource close failed error=%s", type(error).__name__)


def run(mode, settings, stop):
    if not settings.features:
        log.info("no features opted in; no AWS or DB clients constructed")
        return
    if mode == "scheduler":
        services, clients = {}, []
        try:
            for feature in settings.features:
                services[feature] = build_service(feature)
                client = sqs_client(settings)
                clients.append(client)
                configure_publisher(services[feature], client)
            Scheduler(services, settings).run(stop)
        finally:
            for service in services.values():
                cleanup(service=service)
            for client in clients:
                cleanup(client=client)
        return

    def consume(feature):
        service = client = consumer = None
        try:
            service = build_service(feature)
            client = sqs_client(settings)
            consumer = ResultConsumer(feature, service, client, settings)
            consumer.run(stop)
        except Exception as error:
            log.error("consumer exited feature=%s error=%s", feature, type(error).__name__)
            stop.set()  # unexpected thread death must restart the process, not silently lose a queue
            crashed.set()
        finally:
            # A timed-out daemon may still be inside the SDK. Process exit
            # releases its client without closing it concurrently.
            cleanup(service, None if consumer is not None and consumer.heartbeat_running else client)

    crashed = threading.Event()
    threads = [threading.Thread(target=consume, args=(f,), name=f"results-{f}") for f in settings.features]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if crashed.is_set():
        raise RuntimeError("result consumer thread exited unexpectedly")


def main():
    parser = argparse.ArgumentParser(description="EC2 Discord DB runner (explicit feature opt-in required)")
    parser.add_argument("mode", choices=("scheduler", "results", "meeting-scheduler", "meeting-results"))
    parser.add_argument("--check", action="store_true", help="validate config only; no AWS/DB calls")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        meeting = args.mode.startswith("meeting-")
        if meeting:
            from meeting_share import runner
            settings = runner.load()
        else:
            settings = load_settings()
        if args.check:
            log.info("configuration valid mode=%s", args.mode)
            return 0
        if settings is None:
            return 0
        stop = threading.Event()
        install_signals(stop)
        with ProcessLock(settings.lock_dir, args.mode):
            if meeting:
                runner.run(args.mode, settings, stop)
            else:
                run(args.mode, settings, stop)
        return 0
    except SettingsError as error:
        log.error("configuration invalid: %s", error)
        return 78
    except Exception as error:
        log.error("runner stopped error=%s", type(error).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

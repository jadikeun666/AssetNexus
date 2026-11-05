"""
Guard against a regression found in Fase 4: tests used the real Redis broker,
so post_save signals enqueued messages in the DEV Redis. The dev Dramatiq
worker then failed with DoesNotExist, because the IDs belonged to the
throwaway test database. config/settings/test.py swaps in a StubBroker.

The actor assertion is the one that matters: an actor is bound to the broker
that was active when it was declared, so checking get_broker() alone would
not prove that actor.send() stays inside the process.
"""
import dramatiq
from dramatiq.brokers.stub import StubBroker


def test_active_broker_is_stub_under_pytest():
    assert isinstance(dramatiq.get_broker(), StubBroker)


def test_signal_actors_are_bound_to_stub_broker():
    from apps.deterioration.jobs import recalculate_deterioration_job
    from apps.sensors.jobs import push_anomaly_alert_job

    assert isinstance(push_anomaly_alert_job.broker, StubBroker)
    assert isinstance(recalculate_deterioration_job.broker, StubBroker)

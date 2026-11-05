"""
Settings used by pytest (see pytest.ini). Everything is inherited from dev;
only what tests must NOT share with the running dev stack is overridden.

DRAMATIQ_BROKER -> StubBroker: the post_save signals call actor.send(),
which would otherwise enqueue messages in the dev Redis. The dev worker
picks them up and fails with DoesNotExist, because the IDs belong to the
throwaway test database. Tests call actor.fn() directly (or patch send),
so no real broker is needed.
"""
from .dev import *  # noqa: F401,F403

DRAMATIQ_BROKER = {
    "BROKER": "dramatiq.brokers.stub.StubBroker",
    "OPTIONS": {},
}

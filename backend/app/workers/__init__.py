"""Background workers (Milestone 3+).

Currently hosts the automated pricing scan loop. Workers are started from the
FastAPI lifespan and are safe no-ops when disabled or when their dependencies
(Redis) are unavailable.
"""

from app.workers.fulfillment_worker import FulfillmentWorker
from app.workers.order_poll_worker import OrderPollWorker
from app.workers.pricing_worker import PricingScanWorker

__all__ = ["FulfillmentWorker", "OrderPollWorker", "PricingScanWorker"]

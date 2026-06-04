"""Background workers (Milestone 3+).

Currently hosts the automated pricing scan loop. Workers are started from the
FastAPI lifespan and are safe no-ops when disabled or when their dependencies
(Redis) are unavailable.
"""

from app.workers.pricing_worker import PricingScanWorker

__all__ = ["PricingScanWorker"]

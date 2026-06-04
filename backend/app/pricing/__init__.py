"""Arbitrage & dynamic-pricing engine (Milestone 3).

The pure decision engine lives in :mod:`app.pricing.engine` and is free of any
database or network dependency, so the client's pricing rules can be unit
tested exhaustively. Orchestration (assembling market context from the DB,
persisting history, pushing prices) lives in the pricing service / worker.
"""

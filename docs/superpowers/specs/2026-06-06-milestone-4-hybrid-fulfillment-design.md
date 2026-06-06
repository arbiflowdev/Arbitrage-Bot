# Milestone 4 — Hybrid Inventory & JIT Fulfillment (Design)

Date: 2026-06-06
Status: Approved
Source of truth: `Arbitrage_Platform_Milestone_Plan.docx` (gitignored) — Milestone 4 section.

## Goal
Build the inventory system and automated fulfillment workflows. On every sale,
deliver from our own stock first; if we are out of stock, automatically buy the
cheapest equivalent from another marketplace (JIT), then deliver — all
transaction-safe, with no duplicate deliveries.

## Confirmed decisions
1. **Order intake:** webhook-driven fulfillment + a polling safety net
   (`fetch_orders`) that reconciles any missed webhook.
2. **Fulfillment seams:** `adapter.purchase()` (JIT auto-buy) and
   `adapter.deliver()` (customer delivery) are defined on the adapter interface
   and implemented deterministically in the mock adapter. Live per-marketplace
   wiring is deferred to live-credential integration — same pattern M3 used for
   the competitor offer-book.
3. **Wallet:** enforced simulated balances per `(provider, currency)`, topped up
   via an admin API. JIT validates funds before buying and debits on purchase;
   sales credit. A buy with insufficient funds fails safely (order retried).
4. **Inventory upload:** both TXT (one code per line) and CSV (code + optional
   region/platform/source_cost/currency/notes).

## Core flow (the "hybrid" guarantee)
1. Order arrives (webhook or poll) → persisted to `orders`, deduped on
   `(provider, external_order_id)`.
2. Fulfillment acquires a Redis per-order lock + re-reads the order
   `FOR UPDATE`; short-circuits if already `DELIVERED` (idempotency).
3. **Inventory-first:** atomically claim the next available code for the product
   (`SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` on Postgres; guarded select on
   SQLite).
4. **JIT fallback (empty stock):** pick cheapest source marketplace (M3
   `sku_mappings` + `marketplace_prices` logic, other marketplaces only),
   validate wallet funds, debit wallet, `adapter.purchase()` → code, record the
   `jit_purchase` transaction, create the inventory row.
5. **Deliver** via `adapter.deliver()`; mark order `DELIVERED` + inventory
   `SOLD`; record `sale_revenue` transaction.
6. **Any failure** → release reservation, increment `attempts`, set
   `AWAITING_STOCK`/`FAILED`, enqueue retry. Worker loop never crashes.

## Data model (migration `0004`)
- **inventory**: `product_id` (FK SET NULL), `code` (deliverable; never logged,
  masked in API by default), `status` (available/reserved/sold/invalid),
  `region`, `platform`, `source_cost` (Numeric 12,2), `currency`,
  `reserved_order_id` (FK SET NULL), `reserved_at`, `sold_at`, `batch_id`,
  `notes`, `raw`. Index `(product_id, status)`.
- **orders**: `provider`, `external_order_id`, `marketplace_sku`, `product_id`
  (FK SET NULL), `quantity`, `total`/`currency`, `status`
  (received/processing/awaiting_stock/delivered/failed/cancelled),
  `fulfillment_source` (manual/jit), `inventory_id` (FK SET NULL), `attempts`,
  `last_error`, `received_at`, `delivered_at`, `raw`.
  **UniqueConstraint(provider, external_order_id)**.
- **transactions**: signed ledger — `order_id` (FK SET NULL), `type`
  (sale_revenue/jit_purchase/fee/adjustment/top_up), `provider`, `amount`
  (Numeric 14,2, credit +, debit −), `currency`, `balance_after`, `reference`,
  `notes`, `raw`.
- **wallet_balances**: `provider`, `currency`, `balance` (Numeric 14,2).
  UniqueConstraint(provider, currency). Mutated under row lock.

## Services
- **InventoryService** — `upload` (TXT/CSV parse, per-batch dedupe, blank-skip,
  summary), `reserve_one` (atomic claim), `mark_sold`/`release`/`invalidate`,
  availability counts.
- **WalletService** — `get_balance`, `top_up`, `debit`/`credit` under
  `FOR UPDATE`, raises `InsufficientFunds`; writes a transaction per move.
- **SourcingService** (JIT) — cheapest-supplier selection (lowest base cost,
  other marketplaces), wallet validation + debit, `adapter.purchase()`, creates
  inventory row + `jit_purchase` transaction. Honors `JIT_SOURCE_BUFFER_PERCENT`.
- **FulfillmentService** — the orchestrator (locking, idempotency, hybrid
  decision, delivery, retry/rollback).
- **OrderIntakeService** — idempotent `ingest(NormalizedOrder)`; wired into
  `webhook_service._process` for order events.

## Adapter seam (base + mock + live stubs)
- `async purchase(marketplace_sku, quantity, idempotency_key) -> PurchaseResult`
  (`external_purchase_id`, `code`, `cost`, `currency`).
- `async deliver(external_order_id, code, ...) -> DeliveryResult`
  (`success`, `reference`).
Mock implements both deterministically. Live adapters guard with
`CredentialsNotConfigured` until real wiring lands.

## Workers
- **FulfillmentWorker** — drains Redis `queue:fulfillment` with backoff + a
  periodic `AWAITING_STOCK` sweep. Redis-locked, kill-switch aware.
- **OrderPollWorker** — periodic `fetch_orders` per provider → ingest.

## API (admin-only, `/api/v1`)
- `POST /inventory/upload`, `GET /inventory`, `GET /inventory/summary`,
  `POST /inventory/{id}/invalidate`
- `GET /orders`, `GET /orders/{id}`, `POST /orders/{id}/retry`,
  `POST /orders/ingest`
- `GET /wallet`, `POST /wallet/top-up`, `GET /transactions`

## Config (`.env`)
`FULFILLMENT_ENABLED`, `FULFILLMENT_POLL_INTERVAL_SECONDS`,
`FULFILLMENT_MAX_ATTEMPTS`, `FULFILLMENT_RETRY_BACKOFF_SECONDS`, `JIT_ENABLED`,
`JIT_SOURCE_BUFFER_PERCENT`, `WALLET_ENFORCE`.

## Safety properties (success criteria)
- **No duplicate delivery:** unique `(provider, external_order_id)` + Redis
  per-order lock + idempotent `DELIVERED` short-circuit.
- **Transaction-safe:** wallet debit + inventory claim + order update commit
  atomically; failure rolls back and releases.
- **Row/distributed locking:** `FOR UPDATE` (order/wallet), `SKIP LOCKED`
  (inventory), Redis lock across instances.

## Mapping to plan-doc M4 (every deliverable covered)
CSV/TXT uploads, inventory APIs, validation, manual priority, reservation, JIT
sourcing, supplier prioritization, async fulfillment workers, automated
delivery, wallet validation, retry queues, transaction-safe execution,
duplicate prevention, Redis distributed locking, Postgres row locking. Tables:
inventory, orders, transactions, wallet_balances.

## Testing (TDD)
Inventory parse (TXT/CSV/dedupe/blanks); `reserve_one` atomic claim + release;
wallet credit/debit + insufficient funds; sourcing picks cheapest + debits +
creates inventory; fulfillment inventory-first deliver; empty → JIT; duplicate
order not delivered twice; insufficient funds → AWAITING/retry; delivery failure
→ release + retry; order intake idempotency; API (admin gate, upload, list,
top-up).

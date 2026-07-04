"""Inventory management: bulk upload, reservation, and status transitions.

This is the "manual inventory" side of the hybrid pipeline. Codes are uploaded
in bulk (TXT/CSV), held as AVAILABLE, atomically claimed (RESERVED) by the
fulfillment orchestrator, then marked SOLD on successful delivery or released
back to AVAILABLE on failure.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.fulfillment.inventory_parser import parse_inventory
from app.models.inventory import Inventory, InventoryStatus
from app.repositories.inventory_repository import InventoryRepository
from app.schemas.fulfillment import UploadSummary
from app.utils.datetime import utcnow

log = get_logger(__name__)


class InventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = InventoryRepository(session)

    async def upload(
        self,
        product_id: int,
        content: str,
        fmt: str,
        *,
        batch_id: str | None = None,
    ) -> UploadSummary:
        """Parse an upload and persist each new code as AVAILABLE inventory.

        Codes already held for this product (in any status) are skipped rather
        than inserted again: re-uploading the same list must not create duplicate
        AVAILABLE rows, since the repricer mirrors the AVAILABLE count to the
        marketplace as stock and duplicates would silently over-advertise it.
        """
        parsed = parse_inventory(content, fmt)
        bid = batch_id or uuid.uuid4().hex

        # Drop codes we already hold (cross-batch dedup — the parser only
        # de-duplicates within a single upload).
        already = await self.repo.existing_codes(
            product_id, [item.code for item in parsed.items]
        )
        fresh = [item for item in parsed.items if item.code not in already]

        for item in fresh:
            self.session.add(
                Inventory(
                    product_id=product_id,
                    code=item.code,
                    status=InventoryStatus.AVAILABLE,
                    region=item.region,
                    platform=item.platform,
                    source_cost=item.source_cost,
                    currency=item.currency,
                    notes=item.notes,
                    batch_id=bid,
                )
            )
        await self.session.flush()
        # "duplicates" = codes not added because we already have them, whether
        # they repeated within the file (parser) or were already in stock (DB).
        duplicates = parsed.duplicates + len(already)
        log.info(
            "inventory.upload",
            product_id=product_id,
            added=len(fresh),
            duplicates=duplicates,
            skipped=parsed.skipped_blank,
            batch_id=bid,
        )
        return UploadSummary(
            added=len(fresh),
            duplicates=duplicates,
            skipped=parsed.skipped_blank,
            batch_id=bid,
        )

    async def reserve_one(self, product_id: int, order_id: int) -> Inventory | None:
        """Atomically claim the next available code for an order."""
        item = await self.repo.claim_one_available(product_id)
        if item is None:
            return None
        item.status = InventoryStatus.RESERVED
        item.reserved_order_id = order_id
        item.reserved_at = utcnow()
        await self.session.flush()
        return item

    async def mark_sold(self, inventory_id: int) -> Inventory:
        item = await self._get(inventory_id)
        item.status = InventoryStatus.SOLD
        item.sold_at = utcnow()
        await self.session.flush()
        return item

    async def release(self, inventory_id: int) -> Inventory:
        item = await self._get(inventory_id)
        item.status = InventoryStatus.AVAILABLE
        item.reserved_order_id = None
        item.reserved_at = None
        await self.session.flush()
        return item

    async def invalidate(self, inventory_id: int) -> Inventory:
        item = await self._get(inventory_id)
        item.status = InventoryStatus.INVALID
        await self.session.flush()
        return item

    async def available_count(self, product_id: int) -> int:
        return await self.repo.count_status(product_id, InventoryStatus.AVAILABLE)

    async def _get(self, inventory_id: int) -> Inventory:
        item = await self.repo.get_by_id(inventory_id)
        if item is None:
            raise ValueError(f"Inventory {inventory_id} not found.")
        return item

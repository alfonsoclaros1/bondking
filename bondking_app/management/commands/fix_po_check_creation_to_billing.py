from django.core.management.base import BaseCommand
from django.db import transaction

from bondking_app.models import PurchaseOrder, POStatus


class Command(BaseCommand):
    help = "Fix legacy PO.status='CHECK_CREATION' → 'BILLING'"

    @transaction.atomic
    def handle(self, *args, **options):
        # Count first (safety visibility)
        affected = PurchaseOrder.objects.filter(status="CHECK_CREATION").count()

        if affected == 0:
            self.stdout.write(self.style.SUCCESS("✅ No PurchaseOrders need fixing."))
            return

        self.stdout.write(
            self.style.WARNING(
                f"⚠️ Found {affected} PurchaseOrder(s) with invalid status 'CHECK_CREATION'."
            )
        )

        # Update ONLY the status field
        updated = (
            PurchaseOrder.objects
            .filter(status="CHECK_CREATION")
            .update(status=POStatus.BILLING)
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"✅ Updated {updated} PurchaseOrder(s): CHECK_CREATION → BILLING"
            )
        )

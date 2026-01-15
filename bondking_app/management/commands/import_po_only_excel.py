from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
import pandas as pd

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from bondking_app.models import (
    PurchaseOrder,
    PurchaseOrderParticular,
    ProductID,
    Billing,
    POStatus,
    POApprovalStatus,
    BillingStatus,
)

User = get_user_model()


# -------------------------
# Helpers
# -------------------------
def norm_str(x) -> str:
    if pd.isna(x) or x is None:
        return ""
    return str(x).strip()


def norm_upper(x) -> str:
    return norm_str(x).upper()


def to_bool(x, default=False) -> bool:
    if pd.isna(x) or x is None:
        return default
    if isinstance(x, bool):
        return x
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    return default


def to_int(x, default=0) -> int:
    if pd.isna(x) or x is None or str(x).strip() == "":
        return default
    return int(float(x))


def to_decimal(x, default=Decimal("0.00")) -> Decimal:
    if pd.isna(x) or x is None or str(x).strip() == "":
        return default
    return Decimal(str(x))


def to_date(x):
    if pd.isna(x) or x is None or str(x).strip() == "":
        return None
    try:
        return pd.to_datetime(x, dayfirst=True).date()
    except Exception:
        return None


def require_cols(df: pd.DataFrame, required: set[str], sheet: str):
    missing = required - set(df.columns)
    if missing:
        raise Exception(
            f"[{sheet}] Missing required columns: {sorted(missing)}\n"
            f"[{sheet}] Columns found: {list(df.columns)}"
        )


def get_sheet(all_sheets: dict[str, pd.DataFrame], name: str) -> pd.DataFrame | None:
    if name in all_sheets:
        return all_sheets[name]
    lower = {k.lower(): k for k in all_sheets.keys()}
    key = lower.get(name.lower())
    return all_sheets.get(key) if key else None


def aware_midnight(d) -> datetime:
    # store as midnight in your server timezone (Django tz)
    # NOTE: Billing.created_at is auto_now_add; we’ll set via queryset.update() after create.
    dt = datetime.combine(d, time.min)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


@dataclass
class ImportStats:
    po_created: int = 0
    po_updated: int = 0
    particulars_created: int = 0
    billings_created: int = 0
    billings_skipped_existing: int = 0
    po_skipped_no_number: int = 0


# -------------------------
# Command
# -------------------------
class Command(BaseCommand):
    help = "Import ONLY Purchase Orders + Particulars from an Excel file; create Billings from MOP/CHECK#."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=str, required=True)
        parser.add_argument("--sheet", type=str, default="PO")
        parser.add_argument("--dry-run", action="store_true", help="Validate and print counts only (no DB writes).")

        # Safety switches (off by default)
        parser.add_argument(
            "--replace-particulars",
            action="store_true",
            help="If set: delete and recreate particulars for each imported PO (PO-scoped only).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        excel_path: str = options["file"]
        sheet_name: str = options["sheet"]
        dry_run: bool = options["dry_run"]
        replace_particulars: bool = options["replace_particulars"]

        # -------------------------
        # Load sheet
        # -------------------------
        all_sheets = pd.read_excel(excel_path, sheet_name=None)
        df_po = get_sheet(all_sheets, sheet_name)

        if df_po is None or len(df_po) == 0:
            raise Exception(f"Missing or empty sheet: {sheet_name}")

        # Trim column headers
        df_po.columns = [str(c).strip() for c in df_po.columns]

        # Required columns (based on your existing PO importer)
        require_cols(
            df_po,
            {
                "po_number",
                "date",
                "product_id",
                "paid_to",
                "particular",
                "qty",
                "cost",
                "AMOUNT",
                "MOP/CHECK#",
                "STATUS",
                "is_archived",
                "is_cancelled",
            },
            sheet_name,
        )

        # Use/ensure legacy_import user (PO FKs)
        legacy_user, created = User.objects.get_or_create(
            username="legacy_import",
            defaults={"is_active": True, "is_staff": True},
        )
        if created:
            legacy_user.set_unusable_password()
            legacy_user.save(update_fields=["password"])

        status_allowed = {c[0] for c in POStatus.choices}

        stats = ImportStats()

        # -------------------------
        # Group by po_number
        # -------------------------
        for po_no, rows in df_po.groupby("po_number"):
            po_no = norm_str(po_no)
            if not po_no:
                stats.po_skipped_no_number += 1
                continue

            r0 = rows.iloc[0]

            vendor = norm_str(r0.get("paid_to")) or "UNKNOWN"
            po_date = to_date(r0.get("date")) or timezone.now().date()

            status_raw = norm_upper(r0.get("STATUS"))
            po_status = status_raw if status_raw in status_allowed else POStatus.REQUEST_FOR_PAYMENT

            is_archived = to_bool(r0.get("is_archived"), default=False)
            is_cancelled = to_bool(r0.get("is_cancelled"), default=False)

            # ProductID ref (FK)
            product_code = norm_str(r0.get("product_id"))
            product_id_ref = None
            if product_code:
                product_id_ref, _ = ProductID.objects.get_or_create(
                    code=product_code,
                    defaults={
                        "description": norm_str(r0.get("particular")) or vendor or product_code,
                        "is_active": True,
                    },
                )

            if dry_run:
                continue

            # -------------------------
            # PO UPSERT (NO GLOBAL DELETES)
            # -------------------------
            po, was_created = PurchaseOrder.objects.update_or_create(
                po_number=po_no,
                defaults={
                    "paid_to": vendor,
                    "address": "",
                    "date": po_date,
                    "status": po_status,
                    "approval_status": POApprovalStatus.PENDING,
                    # IMPORTANT: we do NOT use cheque_number anymore
                    "cheque_number": None,
                    "is_archived": is_archived,
                    "is_cancelled": is_cancelled,
                    "total": Decimal("0.00"),
                    "prepared_by": legacy_user,
                    "checked_by": legacy_user,
                    "approved_by": legacy_user,
                    "rfp_number": norm_str(r0.get("rfp_number")) or None,
                    "product_id_ref": product_id_ref,
                },
            )

            if was_created:
                stats.po_created += 1
            else:
                stats.po_updated += 1

            # -------------------------
            # Particulars: replace per-PO (only if flag is set)
            # -------------------------
            if replace_particulars:
                po.particulars.all().delete()

            running_total = Decimal("0.00")

            for _, rr in rows.iterrows():
                particular = norm_str(rr.get("particular")) or "PARTICULAR"

                qty = None if pd.isna(rr.get("qty")) else to_int(rr.get("qty"), default=0)
                unit_price = None if pd.isna(rr.get("cost")) else to_decimal(rr.get("cost"))
                total_price = None if pd.isna(rr.get("AMOUNT")) else to_decimal(rr.get("AMOUNT"))

                # If not replacing, we still add; but for reruns that may duplicate.
                # Recommendation: run with --replace-particulars for idempotency.
                PurchaseOrderParticular.objects.create(
                    purchase_order=po,
                    particular=particular,
                    quantity=qty,
                    unit_price=unit_price,
                    total_price=total_price,
                )
                stats.particulars_created += 1

                if total_price:
                    running_total += total_price

            po.total = running_total.quantize(Decimal("0.01"))
            po.save(update_fields=["total"])

            # -------------------------
            # Billing creation from MOP/CHECK# (non-destructive)
            # -------------------------
            check_no = norm_str(r0.get("MOP/CHECK#"))
            if check_no:
                # Don’t create duplicates for same PO + check number (and not cancelled)
                exists = po.billings.filter(is_cancelled=False, check_number=check_no).exists()

                if exists:
                    stats.billings_skipped_existing += 1
                else:
                    billing_status = (
                        BillingStatus.PAID
                        if po.status == POStatus.PO_FILING
                        else BillingStatus.CHECK_CREATION
                    )

                    # Avoid Billing.save() bug by explicitly setting billing_number ourselves
                    billing_number = Billing.get_next_billing_number(po)

                    b = Billing.objects.create(
                        billing_number=billing_number,
                        source_po=po,
                        amount=po.total,
                        check_number=check_no,
                        status=billing_status,
                        is_cancelled=False,
                    )

                    # created_at is auto_now_add, so we set it after create via update()
                    Billing.objects.filter(billing_number=b.billing_number).update(
                        created_at=aware_midnight(po.date)
                    )

                    stats.billings_created += 1

        # Dry-run output (no writes)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no database writes were made."))

        self.stdout.write(self.style.SUCCESS("✅ PO-only import complete."))
        self.stdout.write(
            f"PO created: {stats.po_created} | updated: {stats.po_updated} | "
            f"particulars created: {stats.particulars_created} | "
            f"billings created: {stats.billings_created} | "
            f"billings skipped (existing): {stats.billings_skipped_existing} | "
            f"PO skipped (no number): {stats.po_skipped_no_number}"
        )

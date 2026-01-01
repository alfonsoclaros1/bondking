import re
from datetime import timedelta
from decimal import Decimal

import pandas as pd
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from bondking_app.models import (
    Client,
    Product,
    ProductID,
    DeliveryReceipt,
    DeliveryReceiptItem,
    InventoryIssuance,
    InventoryIssuanceItem,
    PurchaseOrder,
    PurchaseOrderParticular,
    # choices:
    DeliveryStatus,
    PaymentStatus,
    DeliveryMethod,
    PaymentMethod,
    ApprovalStatus,
    POStatus,
    POApprovalStatus,
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
        return pd.to_datetime(x).date()
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
    # exact match first, then case-insensitive
    if name in all_sheets:
        return all_sheets[name]
    lower = {k.lower(): k for k in all_sheets.keys()}
    key = lower.get(name.lower())
    return all_sheets.get(key) if key else None



def safe_choice(value: str, allowed: set[str], default: str):
    v = norm_upper(value)
    return v if v in allowed else default


# -------------------------
# Command
# -------------------------
class Command(BaseCommand):
    help = "Import Bondking Excel (multi-sheet) strictly following models.py + workbook schema."

    def add_arguments(self, parser):
        parser.add_argument("--file", type=str, required=True)
        parser.add_argument("--wipe", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        excel_path = options["file"]
        wipe = options["wipe"]

        # -------------------------
        # Load ALL sheets
        # -------------------------
        all_sheets = pd.read_excel(excel_path, sheet_name=None)

        self.stdout.write("📄 Sheets detected:")
        for name in all_sheets.keys():
            self.stdout.write(f" - {name}")

        # pull required sheets
        df_clients = get_sheet(all_sheets, "clients")
        df_products = get_sheet(all_sheets, "products")
        df_users = get_sheet(all_sheets, "Users")

        df_dr = get_sheet(all_sheets, "DeliveryReceipt")
        df_dri = get_sheet(all_sheets, "DeliveryReceiptItems")

        df_inv = get_sheet(all_sheets, "Inventory")
        df_inv_items = get_sheet(all_sheets, "InventoryIssuanceItem")

        df_po = get_sheet(all_sheets, "PO")

        # normalize column names (trim only, preserve exact names after trimming)
        def trim_cols(df):
            if df is None:
                return None
            df.columns = [str(c).strip() for c in df.columns]
            return df

        df_clients = trim_cols(df_clients)
        df_products = trim_cols(df_products)
        df_users = trim_cols(df_users)
        df_dr = trim_cols(df_dr)
        df_dri = trim_cols(df_dri)
        df_inv = trim_cols(df_inv)
        df_inv_items = trim_cols(df_inv_items)
        df_po = trim_cols(df_po)

        # -------------------------
        # Wipe (FK-safe)
        # -------------------------
        if wipe:
            self.stdout.write(self.style.WARNING("⚠️ WIPING EXISTING DATA…"))

            # break self-FK protection first
            DeliveryReceipt.objects.update(source_dr=None)

            # DR
            DeliveryReceiptItem.objects.all().delete()
            DeliveryReceipt.objects.all().delete()

            # Inventory
            InventoryIssuanceItem.objects.all().delete()
            InventoryIssuance.objects.all().delete()

            # PO
            PurchaseOrderParticular.objects.all().delete()
            PurchaseOrder.objects.all().delete()

            # Clients (keep D2D STOCKS if you rely on it; otherwise delete all)
            Client.objects.exclude(company_name="D2D STOCKS").delete()

            # Products: you said products are okay — but since we’re “overwrite from Excel”,
            # we will upsert products, not delete them.
            self.stdout.write(self.style.SUCCESS("✅ Wipe complete."))

        # -------------------------
        # Ensure legacy_import user exists
        # -------------------------
        legacy_user, created = User.objects.get_or_create(
            username="legacy_import",
            defaults={"is_active": True, "is_staff": True},
        )
        if created:
            legacy_user.set_unusable_password()
            legacy_user.save(update_fields=["password"])

        # -------------------------
        # 1) Users
        # -------------------------
        user_cache: dict[str, User] = {"legacy_import": legacy_user}

        if df_users is not None and len(df_users) > 0:
            require_cols(df_users, {"username", "is_active"}, "Users")
            self.stdout.write("👤 Importing Users…")

            for _, r in df_users.iterrows():
                username = norm_str(r.get("username"))
                if not username:
                    continue

                first_name = norm_str(r.get("first_name"))
                last_name = norm_str(r.get("last_name"))
                email = norm_str(r.get("email"))
                is_active = to_bool(r.get("is_active"), default=True)
                group_name = norm_str(r.get("group"))

                u, was_created = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "first_name": first_name,
                        "last_name": last_name,
                        "email": email,
                        "is_active": is_active,
                    },
                )
                if not was_created:
                    # update basic fields
                    u.first_name = first_name
                    u.last_name = last_name
                    u.email = email
                    u.is_active = is_active
                    u.save(update_fields=["first_name", "last_name", "email", "is_active"])

                if was_created:
                    u.set_unusable_password()
                    u.save(update_fields=["password"])

                if group_name:
                    g, _ = Group.objects.get_or_create(name=group_name)
                    u.groups.add(g)

                user_cache[username] = u

            self.stdout.write(self.style.SUCCESS(f"Users ready: {len(user_cache)}"))
        else:
            self.stdout.write("👤 Users sheet missing/empty → using legacy_import for all user FKs.")

        # -------------------------
        # 2) Clients
        # -------------------------
        if df_clients is None:
            raise Exception("Missing required sheet: clients")

        require_cols(
            df_clients,
            {
                "company_name",
                "street_number",
                "street_name",
                "barangay",
                "city_municipality",
                "province_state",
            },
            "clients",
        )

        self.stdout.write("🏢 Importing Clients…")
        client_cache: dict[str, Client] = {}

        for _, r in df_clients.iterrows():
            company_name = norm_str(r.get("company_name"))
            if not company_name:
                continue
            key = company_name.strip().upper()
            raw_since = norm_str(r.get("since"))
            since = raw_since[:4] if raw_since.isdigit() else None


            client, _ = Client.objects.update_or_create(
                company_name=company_name,
                defaults={
                    "name_of_owner": norm_str(r.get("name_of_owner")),
                    "rented": to_bool(r.get("rented"), default=False),
                    "since": since,
                    "unit_room": norm_str(r.get("unit_room")),
                    "street_number": norm_str(r.get("street_number")),
                    "street_name": norm_str(r.get("street_name")),
                    "barangay": norm_str(r.get("barangay")),
                    "city_municipality": norm_str(r.get("city_municipality")),
                    "province_state": norm_str(r.get("province_state")),
                    "postal_code": norm_str(r.get("postal_code")),
                    "contact_number": norm_str(r.get("contact_number")),
                    "preferred_mop": norm_str(r.get("preferred_mop")),
                },
            )
            client_cache[key] = client

        self.stdout.write(self.style.SUCCESS(f"Clients imported: {len(client_cache)}"))

        # -------------------------
        # 3) Products
        # -------------------------
        if df_products is not None and len(df_products) > 0:
            require_cols(df_products, {"sku", "name", "unit", "default_unit_price"}, "products")
            self.stdout.write("📦 Importing Products…")

            for _, r in df_products.iterrows():
                sku = norm_str(r.get("sku"))
                if not sku:
                    continue

                Product.objects.update_or_create(
                    sku=sku,
                    defaults={
                        "name": norm_str(r.get("name")),
                        "unit": norm_str(r.get("unit")),
                        "default_unit_price": (
                            None if pd.isna(r.get("default_unit_price")) else to_decimal(r.get("default_unit_price"))
                        ),
                    },
                )

            self.stdout.write(self.style.SUCCESS("Products imported/updated."))
        else:
            self.stdout.write("📦 products sheet missing/empty → leaving existing products as-is.")

        # cache products by sku (strict)
        product_by_sku = {p.sku: p for p in Product.objects.all()}

        # -------------------------
        # 5) DeliveryReceipt headers
        # -------------------------
        if df_dr is None:
            raise Exception("Missing required sheet: DeliveryReceipt")

        # IMPORTANT: your sheet uses 'client' (not company_name)
        # and has 'Payment Details' with trailing space in your file.
        require_cols(
            df_dr,
            {"dr_number", "client", "date_of_order", "agent", "delivery_method", "payment_method"},
            "DeliveryReceipt",
        )

        # Allowed choices based on your models.py
        delivery_status_allowed = {c[0] for c in DeliveryStatus.choices}
        payment_status_allowed = {c[0] for c in PaymentStatus.choices}
        delivery_method_allowed = {c[0] for c in DeliveryMethod.choices}
        payment_method_allowed = {c[0] for c in PaymentMethod.choices}
        approval_allowed = {c[0] for c in ApprovalStatus.choices}

        self.stdout.write("🚚 Importing DeliveryReceipt headers…")
        dr_by_number: dict[str, DeliveryReceipt] = {}

        for _, r in df_dr.iterrows():
            dr_number = norm_str(r.get("dr_number"))
            if not dr_number:
                continue

            client_key = norm_upper(r.get("client"))
            client_obj = client_cache.get(client_key)
            if not client_obj:
                raise Exception(f"[DeliveryReceipt] Unknown client='{client_key}' for DR={dr_number}")

            # Users
            agent_username = norm_str(r.get("agent"))
            created_by_username = norm_str(r.get("created_by"))
            agent = user_cache.get(agent_username) or legacy_user
            created_by = user_cache.get(created_by_username) or legacy_user

            date_of_order = to_date(r.get("date_of_order")) or timezone.now().date()
            date_of_delivery = to_date(r.get("date_of_delivery"))

            raw_delivery_status = norm_str(r.get("delivery_status"))
            raw_is_cancelled = to_bool(r.get("is_cancelled"), default=False)

            # Your sheet sometimes uses "Cancelled" (not a model choice)
            # We convert it into is_cancelled=True and set delivery_status safely.
            is_cancelled = raw_is_cancelled or (raw_delivery_status.strip().lower() == "cancelled")

            delivery_status = safe_choice(raw_delivery_status, delivery_status_allowed, DeliveryStatus.NEW_DR)
            if raw_delivery_status.strip().lower() == "cancelled":
                delivery_status = DeliveryStatus.NEW_DR

            payment_status = safe_choice(norm_str(r.get("payment_status")), payment_status_allowed, PaymentStatus.NA)

            delivery_method = safe_choice(norm_str(r.get("delivery_method")), delivery_method_allowed, DeliveryMethod.DELIVERY)
            payment_method = safe_choice(norm_str(r.get("payment_method")), payment_method_allowed, PaymentMethod.CASH)

            approval_status = safe_choice(norm_str(r.get("approval_status")), approval_allowed, ApprovalStatus.PENDING)

            is_archived = to_bool(r.get("is_archived"), default=False)


            payment_details = norm_str(r.get("Payment Details"))  # after trim_cols, trailing space is removed

            dr, _ = DeliveryReceipt.objects.update_or_create(
                dr_number=dr_number,
                defaults={
                    "client": client_obj,
                    "date_of_order": date_of_order,
                    "date_of_delivery": date_of_delivery,
                    "due_date": None,          # computed later
                    "payment_due": None,       # computed later
                    "delivery_status": delivery_status,
                    "payment_status": payment_status,
                    "delivery_method": delivery_method,
                    "agent": agent,
                    "payment_method": payment_method,
                    "payment_details": payment_details,
                    "remarks": norm_str(r.get("remarks")),
                    "total_amount": Decimal("0.00"),  # computed after items
                    "created_by": created_by,
                    "approval_status": approval_status,
                    "is_archived": is_archived,
                    "is_cancelled": is_cancelled,
                    "source_dr": None,
                    "proof_of_delivery": None,
                    "sales_invoice_no": None,
                    "deposit_slip_no": None,
                },
            )
            dr_by_number[dr_number] = dr

        self.stdout.write(self.style.SUCCESS(f"DeliveryReceipts imported: {len(dr_by_number)}"))

        # -------------------------
        # 6) DeliveryReceiptItems
        # -------------------------
        if df_dri is None:
            raise Exception("Missing required sheet: DeliveryReceiptItems")

        # your sheet uses 'product' as SKU
        require_cols(df_dri, {"dr_number", "product", "quantity", "unit_price"}, "DeliveryReceiptItems")

        self.stdout.write("🧾 Importing DeliveryReceiptItems…")

        # clear existing items for DRs just imported (if not wiped)
        # to avoid duplicates if you re-run without --wipe
        if not wipe:
            DeliveryReceiptItem.objects.filter(delivery_receipt__dr_number__in=list(dr_by_number.keys())).delete()

        item_count = 0
        totals_by_dr: dict[str, Decimal] = {}

        for _, r in df_dri.iterrows():
            dr_number = norm_str(r.get("dr_number"))
            sku = norm_str(r.get("product"))
            if not dr_number or not sku:
                continue

            dr = dr_by_number.get(dr_number)
            if not dr:
                raise Exception(f"[DeliveryReceiptItems] DR not found in headers: {dr_number}")

            product = product_by_sku.get(sku)
            if not product:
                raise Exception(f"[DeliveryReceiptItems] Unknown product SKU: {sku}")

            qty = to_int(r.get("quantity"), default=0)
            unit_price = to_decimal(r.get("unit_price"), default=Decimal("0.00"))

            item = DeliveryReceiptItem.objects.create(
                delivery_receipt=dr,
                product=product,
                description=product.name,   # model has description; not in sheet
                quantity=qty,
                unit_price=unit_price,
                line_total=Decimal("0.00"), # model has line_total; will recalc in save if implemented
            )

            # If your model doesn't auto-calc line_total, compute here
            line_total = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))
            if item.line_total != line_total:
                item.line_total = line_total
                item.save(update_fields=["line_total"])

            totals_by_dr[dr_number] = totals_by_dr.get(dr_number, Decimal("0.00")) + line_total
            item_count += 1

        self.stdout.write(self.style.SUCCESS(f"DeliveryReceiptItems imported: {item_count}"))

        # -------------------------
        # 7) Finalize DR computed fields: total_amount, payment_due, due_date
        # -------------------------
        self.stdout.write("🧮 Finalizing DR totals and due dates…")

        term_days = {
            PaymentMethod.DAYS_15: 15,
            PaymentMethod.DAYS_30: 30,
            PaymentMethod.DAYS_60: 60,
            PaymentMethod.DAYS_90: 90,
            PaymentMethod.DAYS_120: 120,
        }

        for dr_number, dr in dr_by_number.items():
            total = totals_by_dr.get(dr_number, Decimal("0.00")).quantize(Decimal("0.01"))
            dr.total_amount = total

            # compute payment_due and due_date for term-based methods
            base = dr.date_of_delivery or dr.date_of_order
            days = term_days.get(dr.payment_method)

            if days:
                pdue = base + timedelta(days=days)
                dr.payment_due = pdue
                dr.due_date = pdue
            else:
                dr.payment_due = None
                dr.due_date = None

            dr.save(update_fields=["total_amount", "payment_due", "due_date"])

        self.stdout.write(self.style.SUCCESS("✅ DR totals/due dates updated."))

        # -------------------------
        # 8) Inventory Issuance + Items
        # -------------------------
        inv_map: dict[str, InventoryIssuance] = {}

        if df_inv is not None and len(df_inv) > 0:
            require_cols(df_inv, {"issuance_ref", "Date", "issuance_type", "created_by_username", "is_pending", "is_cancelled", "remarks"}, "Inventory")

            self.stdout.write("🏗️ Importing InventoryIssuance…")

            for _, r in df_inv.iterrows():
                issuance_ref = norm_str(r.get("issuance_ref")) or norm_str(r.get("Issuance"))
                if not issuance_ref:
                    continue

                itype_raw = norm_str(r.get("issuance_type"))
                if itype_raw == "TF to WH":
                    itype = InventoryIssuance.TF_TO_WH
                elif itype_raw == "WH to HQ":
                    itype = InventoryIssuance.WH_TO_HQ
                else:
                    raise Exception(f"[Inventory] Unknown issuance_type: {itype_raw}")

                created_by_username = norm_str(r.get("created_by_username"))
                created_by = user_cache.get(created_by_username) or legacy_user

                issuance = InventoryIssuance.objects.create(
                    issuance_type=itype,
                    created_by=created_by,
                    is_pending=to_bool(r.get("is_pending"), default=True),
                    is_cancelled=to_bool(r.get("is_cancelled"), default=False),
                    remarks=norm_str(r.get("remarks")),
                )
                inv_map[issuance_ref] = issuance

            self.stdout.write(self.style.SUCCESS(f"InventoryIssuance imported: {len(inv_map)}"))
        else:
            self.stdout.write("🏗️ Inventory sheet missing/empty → skipping InventoryIssuance.")

        if df_inv_items is not None and len(df_inv_items) > 0:
            require_cols(df_inv_items, {"issuance_ref", "product_sku", "quantity"}, "InventoryIssuanceItem")

            self.stdout.write("🏗️ Importing InventoryIssuanceItem…")
            inv_item_count = 0

            for _, r in df_inv_items.iterrows():
                issuance_ref = norm_str(r.get("issuance_ref"))
                sku = norm_str(r.get("product_sku"))
                if not issuance_ref or not sku:
                    continue

                issuance = inv_map.get(issuance_ref)
                if not issuance:
                    raise Exception(f"[InventoryIssuanceItem] Unknown issuance_ref: {issuance_ref}")

                product = product_by_sku.get(sku)
                if not product:
                    raise Exception(f"[InventoryIssuanceItem] Unknown product SKU: {sku}")

                InventoryIssuanceItem.objects.create(
                    issuance=issuance,
                    product=product,
                    quantity=to_int(r.get("quantity"), default=0),
                )
                inv_item_count += 1

            self.stdout.write(self.style.SUCCESS(f"InventoryIssuanceItems imported: {inv_item_count}"))
        else:
            self.stdout.write("🏗️ InventoryIssuanceItem sheet missing/empty → skipping items.")

        # -------------------------
        # 9) Purchase Orders (PO) + Particulars + ProductID mapping
        # -------------------------
        if df_po is not None and len(df_po) > 0:
            require_cols(
                df_po,
                {"PO#", "DATE", "PRODUCT CODE", "VENDOR", "SUBJECT", "QTY", "UNIT COST", "AMOUNT", "MOP/CHECK#", "STATUS"},
                "PO",
            )

            self.stdout.write("💳 Importing PurchaseOrders + Particulars…")

            # group by PO#
            for po_no, rows in df_po.groupby("PO#"):
                po_no = norm_str(po_no)
                if not po_no:
                    continue

                r0 = rows.iloc[0]

                status_raw = norm_upper(r0.get("STATUS"))
                status_allowed = {c[0] for c in POStatus.choices}
                status = status_raw if status_raw in status_allowed else POStatus.REQUEST_FOR_PAYMENT

                prepared_by = legacy_user
                checked_by = legacy_user
                approved_by = legacy_user

                vendor = norm_str(r0.get("VENDOR"))
                subject = norm_str(r0.get("SUBJECT"))

                # ProductID reference (FK) comes from PRODUCT CODE column
                product_code = norm_str(r0.get("PRODUCT CODE"))
                product_id_ref = None
                if product_code:
                    product_id_ref, _ = ProductID.objects.get_or_create(
                        code=product_code,
                        defaults={"description": subject or vendor or product_code, "is_active": True},
                    )

                po = PurchaseOrder.objects.create(
                    paid_to=vendor or "UNKNOWN",
                    address="",  # your Excel doesn’t carry supplier address
                    date=to_date(r0.get("DATE")) or timezone.now().date(),
                    status=status,
                    approval_status=POApprovalStatus.PENDING,
                    cheque_number=norm_str(r0.get("MOP/CHECK#")),
                    is_archived=False,
                    is_cancelled=False,
                    total=Decimal("0.00"),  # will recalc from particulars
                    prepared_by=prepared_by,
                    checked_by=checked_by,
                    approved_by=approved_by,
                    po_number=po_no,
                    rfp_number=None,
                    product_id_ref=product_id_ref,
                )

                # particulars per line
                running_total = Decimal("0.00")

                for _, rr in rows.iterrows():
                    particular = norm_str(rr.get("SUBJECT")) or "PARTICULAR"
                    qty = rr.get("QTY")
                    unit_cost = rr.get("UNIT COST")
                    amount = rr.get("AMOUNT")

                    q = None if pd.isna(qty) else to_int(qty, default=0)
                    up = None if pd.isna(unit_cost) else to_decimal(unit_cost, default=Decimal("0.00"))
                    tp = None if pd.isna(amount) else to_decimal(amount, default=Decimal("0.00"))

                    PurchaseOrderParticular.objects.create(
                        purchase_order=po,
                        particular=particular,
                        quantity=q,
                        unit_price=up,
                        total_price=tp,
                    )

                    if tp is not None:
                        running_total += tp

                po.total = running_total.quantize(Decimal("0.01"))
                po.save(update_fields=["total"])

            self.stdout.write(self.style.SUCCESS("✅ Purchase Orders imported."))
        else:
            self.stdout.write("💳 PO sheet missing/empty → skipping Purchase Orders.")

        self.stdout.write(self.style.SUCCESS("✅ IMPORT COMPLETE (strict, multi-sheet, model-aligned)"))

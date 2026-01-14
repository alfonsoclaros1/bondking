from decimal import ROUND_HALF_UP, Decimal
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


User = settings.AUTH_USER_MODEL

# =========================
#  ROLE / GROUP CONSTANTS
# =========================

SALES_AGENT_GROUP = "SalesAgent"
SALES_HEAD_GROUP = "SalesHead"
LOGISTICS_OFFICER_GROUP = "LogisticsOfficer"
LOGISTICS_HEAD_GROUP = "LogisticsHead"
ACCOUNTING_OFFICER_GROUP = "AccountingOfficer"
ACCOUNTING_HEAD_GROUP = "AccountingHead"
TOP_MANAGEMENT_GROUP = "TopManagement"


def user_in_group(user, group_name: str) -> bool:
    if not user.is_authenticated:
        return False
    return user.groups.filter(name=group_name).exists()


def is_sales_agent(user):
    return user_in_group(user, SALES_AGENT_GROUP)


def is_sales_head(user):
    return user_in_group(user, SALES_HEAD_GROUP)


def is_logistics_officer(user):
    return user_in_group(user, LOGISTICS_OFFICER_GROUP)


def is_logistics_head(user):
    return user_in_group(user, LOGISTICS_HEAD_GROUP)


def is_accounting_officer(user):
    return user_in_group(user, ACCOUNTING_OFFICER_GROUP)


def is_accounting_head(user):
    return user_in_group(user, ACCOUNTING_HEAD_GROUP)


def is_top_management(user) -> bool:
    return user.is_superuser or user_in_group(user, TOP_MANAGEMENT_GROUP)

def get_effective_role(request):
    return request.session.get("simulated_role") or get_user_role(request.user)

def get_user_role(user) -> str | None:
    """
    Map a Django user to a logical role string based on their groups.
    """
    if user_in_group(user, SALES_AGENT_GROUP):
        return "SalesAgent"
    if user_in_group(user, SALES_HEAD_GROUP):
        return "SalesHead"
    if user_in_group(user, LOGISTICS_OFFICER_GROUP):
        return "LogisticsOfficer"
    if user_in_group(user, LOGISTICS_HEAD_GROUP):
        return "LogisticsHead"
    if user_in_group(user, ACCOUNTING_OFFICER_GROUP):
        return "AccountingOfficer"
    if user_in_group(user, ACCOUNTING_HEAD_GROUP):
        return "AccountingHead"
    if user_in_group(user, TOP_MANAGEMENT_GROUP):
        return "TopManagement"
    return None

# Inventory Issuance permissions (EXTENSIBLE)
INVENTORY_ISSUANCE_EDIT_ROLES = {"AGR"}

def can_manage_inventory_issuance(user):
    role = get_user_role(user)
    return user.is_superuser or role in INVENTORY_ISSUANCE_EDIT_ROLES

# ================  ENUM CHOICES  ================

class DeliveryStatus(models.TextChoices):
    NEW_DR = "NEW_DR", "New DR"
    FOR_DELIVERY = "FOR_DELIVERY", "For Delivery"
    DELIVERED = "DELIVERED", "Delivered"


class PaymentStatus(models.TextChoices):
    NA = "NA", "N/A"
    FOR_COUNTER_CREATION = "FOR_COUNTER_CREATION", "For Counter Creation"
    FOR_COUNTERING = "FOR_COUNTERING", "For Countering"
    COUNTERED = "COUNTERED", "Countered"
    FOR_COLLECTION = "FOR_COLLECTION", "For Collection"
    FOR_DEPOSIT = "FOR_DEPOSIT", "For Deposit"
    DEPOSITED = "DEPOSITED", "Deposited"


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Cash"
    DAYS_15 = "DAYS_15", "15 days"
    DAYS_30 = "DAYS_30", "30 days"
    DAYS_60 = "DAYS_60", "60 days"
    DAYS_90 = "DAYS_90", "90 days"
    DAYS_120 = "DAYS_120", "120 days"


class ApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    DECLINED = "DECLINED", "Declined"


class DeliveryMethod(models.TextChoices):
    DELIVERY = "DELIVERY", "Delivery"
    D2D_STOCKS = "D2D_STOCKS", "D2D Stocks"
    DOOR_TO_DOOR = "DOOR_TO_DOOR", "Door to Door"
    SAMPLE = "SAMPLE", "Sample"


class InventoryIssuanceType(models.TextChoices):
    TF_TO_WH = "TF_WH", "TF to WH"
    WH_TO_HQ = "WH_HQ", "WH to HQ"
    DELIVERED = "DELIVERED", "Delivered"

class POStatus(models.TextChoices):
    REQUEST_FOR_PAYMENT = "REQUEST_FOR_PAYMENT", "Request for Payment"
    REQUEST_FOR_PAYMENT_APPROVAL = "REQUEST_FOR_PAYMENT_APPROVAL", "Request for Payment (Approval)"
    PURCHASE_ORDER = "PURCHASE_ORDER", "Purchase Order"
    PURCHASE_ORDER_APPROVAL = "PURCHASE_ORDER_APPROVAL", "Purchase Order (Approval)"
    BILLING = "BILLING", "Billing"
    PO_FILING = "PO_FILING", "PO Filing"
    ARCHIVED = "ARCHIVED", "Archived"

    
class POApprovalStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    DECLINED = "DECLINED", "Declined"


# =========================
#  KANBAN COLUMNS
# =========================

KANBAN_COLUMNS = [
    "NEW_DR",
    "FOR_DELIVERY",
    "DELIVERED",
    "FOR_COUNTER_CREATION",
    "FOR_COUNTERING",
    "COUNTERED",
    "FOR_COLLECTION",
    "FOR_DEPOSIT",
    "DEPOSITED",
]

COLUMN_INDEX = {col: idx for idx, col in enumerate(KANBAN_COLUMNS)}

PO_FLOW = [
    "REQUEST_FOR_PAYMENT",
    "REQUEST_FOR_PAYMENT_APPROVAL",
    "PURCHASE_ORDER",
    "PURCHASE_ORDER_APPROVAL",
    "BILLING",
    "PO_FILING",
]
PO_COLUMN_INDEX = {col: idx for idx, col in enumerate(PO_FLOW)}


AGR_GROUP = "AGR"
RVT_GROUP = "RVT"
JGG_GROUP = "JGG"

def is_agr(user): return user_in_group(user, AGR_GROUP)
def is_rvt(user): return user_in_group(user, RVT_GROUP)
def is_jgg(user): return user_in_group(user, JGG_GROUP)


# ==========  CORE DATA MODELS  ==========

class Client(models.Model):
    company_name = models.CharField(max_length=255)
    name_of_owner = models.CharField(max_length=255, blank=True)
    rented = models.BooleanField(default=False)
    since = models.CharField(max_length=4,blank=True,null=True,help_text="Year since the client started, e.g., 2015")
    unit_room = models.CharField(
        max_length=50,
        blank=True,
        help_text="Unit, room, floor, or apartment number"
    )
    street_number = models.CharField(
        max_length=150,
        blank=True,
        help_text="House or building number"
    )
    street_name = models.CharField(
        max_length=255,
    )
    barangay = models.CharField(
        max_length=255,
        blank=True,
    )
    city_municipality = models.CharField(
        max_length=255
    )
    province_state = models.CharField(
        max_length=255
    )
    postal_code = models.CharField(
        max_length=20,
    )

    contact_number = models.CharField(max_length=50, blank=True)
    preferred_mop = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        blank=True,
    )    
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clients",
        help_text="Assigned sales agent"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def full_address(self):
        parts = [
            self.unit_room,
            self.street_number,
            self.street_name,
            self.barangay,
            self.city_municipality,
            self.province_state,
            self.postal_code,
        ]
        return ", ".join(filter(None, parts))


    def __str__(self):
        return self.company_name



class ProductID(models.Model):
    code = models.CharField(
        max_length=50,
        unique=True,
        help_text="Product / Project / Cost Code",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.code


class Product(models.Model):
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=50)  # e.g. pcs, box, bottle, etc.
    default_unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    def __str__(self):
        return f"{self.sku} - {self.name}"

    
# =========================
#  DR STEP META (AUTHORITATIVE)
# =========================

DR_STEP_META = {
    "NEW_DR": {
        "label": "New DR",
        "next_action": "Submit DR to start processing.",
        # Roles allowed to move forward FROM this column
        "forward_roles": {"SalesAgent", "SalesHead", "TopManagement"},
        # Roles allowed to move backward FROM this column
        "backward_roles": set(),
        # Roles allowed to approve/decline WHILE in this column
        "approver_roles": {"SalesHead", "TopManagement"},
        "decliner_roles": {"SalesHead", "TopManagement"},
        # Required fields to ENTER or remain valid in this step (UI/helper use)
        "required_fields": ["date_of_order", "client", "payment_method", "delivery_method"],
        # Required fields to move forward out of this step (transition-enforced)
        "required_before_forward": [],  # none specific in your current code
        # Mapping: what statuses represent this column
        "status_map": {"delivery_status": DeliveryStatus.NEW_DR, "payment_status": PaymentStatus.NA},
        # When moving forward into this column, should approval become PENDING?
        "approval_on_enter_forward": True,
        # When moving forward into this column, should approval become APPROVED?
        "auto_approve_on_enter_forward": False,
    },

    "FOR_DELIVERY": {
        "label": "For Delivery",
        "next_action": "Logistics sets Delivery Date then marks Delivered.",
        "forward_roles": {"LogisticsOfficer", "LogisticsHead", "TopManagement"},
        "backward_roles": {"SalesHead", "LogisticsHead", "TopManagement"},
        "approver_roles": {"LogisticsHead", "TopManagement"},
        "decliner_roles": {"LogisticsHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward":["date_of_delivery"],
        "status_map": {"delivery_status": DeliveryStatus.FOR_DELIVERY, "payment_status": PaymentStatus.NA},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "DELIVERED": {
        "label": "Delivered",
        "next_action": "Route to countering steps (Terms) or to Deposit (Cash).",
        # In your current code, Delivery can move it forward. For Door-to-Door, Sales is allowed forward too.
        "forward_roles": {"LogisticsOfficer", "LogisticsHead", "TopManagement"},
        "backward_roles": {"LogisticsHead", "TopManagement"},
        "approver_roles": {"LogisticsHead", "TopManagement"},
        # You didn’t include DELIVERED in decline map except the D2D special-case; we keep that behavior.
        "decliner_roles": set(),
        "required_fields": [],
        "required_before_forward": [],  # branching handled in flow logic
        "status_map": {"delivery_status": DeliveryStatus.DELIVERED, "payment_status": PaymentStatus.NA},
        # Important: in your current code, forward into DELIVERED ends up APPROVED.
        "approval_on_enter_forward": False,          # don’t force pending when entering delivered
        "auto_approve_on_enter_forward": True,       # match: if is_forward -> approval approved
    },

    "FOR_COUNTER_CREATION": {
        "label": "For Counter Creation",
        "next_action": "Accounting sets Payment Due then forwards to Countering.",
        "forward_roles": {"AccountingOfficer", "AccountingHead", "TopManagement"},
        "backward_roles": {"AccountingHead", "TopManagement"},
        "approver_roles": {"AccountingHead", "TopManagement"},
        "decliner_roles": {"AccountingHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward":[],  # matches your current precondition (message typo aside)
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.FOR_COUNTER_CREATION},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "FOR_COUNTERING": {
        "label": "For Countering",
        "next_action": "Logistics counters the receipt.",
        "forward_roles": {"LogisticsOfficer", "LogisticsHead", "TopManagement"},
        "backward_roles": {"LogisticsHead", "TopManagement"},
        "approver_roles": {"LogisticsHead", "TopManagement"},
        "decliner_roles": {"LogisticsHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward": [],
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.FOR_COUNTERING},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "COUNTERED": {
        "label": "Countered",
        "next_action": "Accounting confirms countered then proceeds to Collection.",
        "forward_roles": {"AccountingOfficer", "AccountingHead", "TopManagement"},
        "backward_roles": {"AccountingHead", "TopManagement"},
        "approver_roles": {"AccountingHead", "TopManagement"},
        "decliner_roles": {"AccountingHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward": [],
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.COUNTERED},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "FOR_COLLECTION": {
        "label": "For Collection",
        "next_action": "Logistics collects and records payment details then forwards to Deposit.",
        "forward_roles": {"LogisticsOfficer", "LogisticsHead", "TopManagement"},
        "backward_roles": {"LogisticsHead", "TopManagement"},
        "approver_roles": {"LogisticsHead", "TopManagement"},
        "decliner_roles": {"LogisticsHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward": ["payment_details"],
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.FOR_COLLECTION},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "FOR_DEPOSIT": {
        "label": "For Deposit",
        "next_action": "Accounting deposits and records payment details, then marks Deposited.",
        "forward_roles": {"AccountingOfficer", "AccountingHead", "TopManagement"},
        "backward_roles": {"AccountingHead", "TopManagement"},
        "approver_roles": {"AccountingHead", "TopManagement"},
        "decliner_roles": {"AccountingHead", "TopManagement"},
        "required_fields": [],
        "required_before_forward": ["payment_details","deposit_slip_no"],  # matches your current precondition
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.FOR_DEPOSIT},
        "approval_on_enter_forward": True,
        "auto_approve_on_enter_forward": False,
    },

    "DEPOSITED": {
        "label": "Deposited",
        "next_action": "Workflow complete.",
        "forward_roles": set(),
        "backward_roles": {"AccountingHead", "TopManagement"},
        "approver_roles": set(),
        "decliner_roles": set(),
        "required_fields": [],
        "required_before_forward": [],
        "status_map": {"delivery_status": None, "payment_status": PaymentStatus.DEPOSITED},
        # In your current code, entering DEPOSITED ends APPROVED.
        "approval_on_enter_forward": False,
        "auto_approve_on_enter_forward": True,
    },
}


class DeliveryReceipt(models.Model):
    """
    DR header. Individual line items are in DeliveryReceiptItem.
    """

    dr_number = models.CharField(
        max_length=20,
        unique=True,
        help_text="Format: YYYY-XXXX (e.g., 2025-0001). Generated by system.",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name="delivery_receipts",
    )
    date_of_order = models.DateField(default=timezone.now)
    date_of_delivery = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)

    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.NEW_DR,
    )
    payment_status = models.CharField(
        max_length=30,
        choices=PaymentStatus.choices,
        default=PaymentStatus.NA,
    )
    delivery_method = models.CharField(
        max_length=20,
        choices=DeliveryMethod.choices,
        default=DeliveryMethod.DELIVERY,
    )
    agent = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="agent_delivery_receipts",
    )  # Sales Agent

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
    )
    payment_details = models.TextField(
        blank=True,
        help_text="Used for notes on partial payments, terms, deposit details, etc.",
    )
    remarks = models.TextField(blank=True)

    payment_due = models.DateField(
        null=True,
        blank=True,
        help_text="Financial due date if needed (separate from delivery due_date).",
    )

    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="created_delivery_receipts",
    )
    approval_status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_archived = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)
    reject_problem = models.TextField(blank=True, default="")
    reject_solution = models.TextField(blank=True, default="")

    source_dr = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="door_to_door_children",
        help_text="Required only for Door to Door DRs. Must reference an D2D Stocks DR (not archived).",
    )
    proof_of_delivery = models.ImageField(
        upload_to="proof_of_delivery/",
        blank=True,
        null=True,
        help_text="Uploaded upon delivery"
    )

    sales_invoice_no = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Optional sales invoice reference"
    )

    deposit_slip_no = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Required before deposit completion"
    )


    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.dr_number} - {self.client.company_name}"

    # ====== Derived helpers ======
    # Which columns exist for each DR type (same as your get_lifecycle_steps)
    @staticmethod
    def dr_lifecycle_for(dr: "DeliveryReceipt") -> list[str]:
        if dr.delivery_method == DeliveryMethod.D2D_STOCKS:
            return ["D2D_STOCKS"]

        pm = dr.payment_method
        dm = dr.delivery_method

        if dm == DeliveryMethod.SAMPLE:
            return ["NEW_DR", "FOR_DELIVERY", "DELIVERED"]
        
        if dm == DeliveryMethod.DOOR_TO_DOOR and pm == PaymentMethod.CASH:
            return ["NEW_DR", "DELIVERED", "FOR_DEPOSIT", "DEPOSITED"]

        if dm == DeliveryMethod.DOOR_TO_DOOR:
            return ["NEW_DR", "DELIVERED", "FOR_COUNTER_CREATION", "FOR_COUNTERING", "COUNTERED",
                    "FOR_COLLECTION", "FOR_DEPOSIT", "DEPOSITED"]

        if pm == PaymentMethod.CASH:
            return ["NEW_DR", "FOR_DELIVERY", "DELIVERED", "FOR_DEPOSIT", "DEPOSITED"]

        return ["NEW_DR", "FOR_DELIVERY", "DELIVERED", "FOR_COUNTER_CREATION", "FOR_COUNTERING", "COUNTERED",
                "FOR_COLLECTION", "FOR_DEPOSIT", "DEPOSITED"]

    def recalc_total_amount(self, save=True):
        total = self.items.aggregate(sum=Sum("line_total"))["sum"] or 0
        self.total_amount = total
        if save:
            self.save(update_fields=["total_amount"])

    def log_update(self, user, message: str, user_notes: str = ""):
        """
        Central logging helper, used by all state-changing operations.
        """
        return DeliveryReceiptUpdate.objects.create(
            delivery_receipt=self,
            user=user,
            system_update=message,
            user_notes=user_notes or "",
        )
    def get_next_step_meta(self):
        _, next_step = self.get_current_and_next_step()
        if not next_step:
            return None
        return DR_STEP_META.get(next_step)


    def get_missing_required_fields(self, step):
        meta = DR_STEP_META.get(step)
        if not meta:
            return []

        missing = []
        for field in meta.get("required_fields", []):
            if not getattr(self, field):
                missing.append(field)
        return missing

    def get_missing_required_before_forward(self):
        """
        Returns a list of fields that must be filled
        before this DR can move forward from the CURRENT step.
        """
        current_step = self.get_current_column()
        meta = DR_STEP_META.get(current_step)

        if not meta:
            return []

        required = meta.get("required_before_forward", [])
        missing = []

        for field in required:
            value = getattr(self, field, None)

            if value in [None, "", []]:
                missing.append(field)

        return missing

    # ====== Kanban / column logic ======

    def get_current_column(self) -> str:
        """
        Map delivery_status + payment_status to a Kanban column key.

        Vision:
        - NEW_DR         -> NEW_DR
        - FOR_DELIVERY   -> FOR_DELIVERY
        - DELIVERED + NA -> DELIVERED
        - Payment stages -> their own columns
        """
        ds = self.delivery_status
        ps = self.payment_status

        if ds == DeliveryStatus.NEW_DR:
            return "NEW_DR"
        if ds == DeliveryStatus.FOR_DELIVERY:
            return "FOR_DELIVERY"
        if ds == DeliveryStatus.DELIVERED and ps == PaymentStatus.NA:
            return "DELIVERED"

        if ps == PaymentStatus.FOR_COUNTER_CREATION:
            return "FOR_COUNTER_CREATION"
        if ps == PaymentStatus.FOR_COUNTERING:
            return "FOR_COUNTERING"
        if ps == PaymentStatus.COUNTERED:
            return "COUNTERED"
        if ps == PaymentStatus.FOR_COLLECTION:
            return "FOR_COLLECTION"
        if ps == PaymentStatus.FOR_DEPOSIT:
            return "FOR_DEPOSIT"
        if ps == PaymentStatus.DEPOSITED:
            return "DEPOSITED"

        # Fallback
        return "NEW_DR"

    def move_to_column(
        self,
        user,
        target_column: str,
        user_notes: str = "",
        simulated_role: str | None = None,
    ):
        # -------------------------------
        # 0. Determine actor role
        # -------------------------------
        if simulated_role and is_top_management(user):
            actor_role = simulated_role
        else:
            actor_role = get_user_role(user)

        if not actor_role:
            raise PermissionDenied("Your account does not have an assigned role.")

        # D2D Stocks is not part of the workflow at all
        if self.delivery_method == DeliveryMethod.D2D_STOCKS:
            raise ValidationError("D2D Stocks DRs are not movable in the Kanban.")

        lifecycle = DeliveryReceipt.dr_lifecycle_for(self)
        if target_column not in lifecycle:
            raise ValidationError("Invalid target column for this DR type.")

        current_column = self.get_current_column()
        if current_column == target_column:
            return

        # Door-to-Door: explicitly forbid FOR_DELIVERY (even if someone tries)
        if self.delivery_method == DeliveryMethod.DOOR_TO_DOOR and target_column == "FOR_DELIVERY":
            raise ValidationError("Door to Door DRs skip For Delivery.")

        # Use lifecycle index for movement direction
        current_idx = lifecycle.index(current_column) if current_column in lifecycle else 0
        target_idx = lifecycle.index(target_column)
        is_forward = target_idx > current_idx
        is_backward = target_idx < current_idx

        pm = str(self.payment_method).upper()
        if self.approval_status == ApprovalStatus.DECLINED and is_forward:
            raise ValidationError(
                "This DR was rejected and must be resolved before moving forward."
            )

        # -------------------------------
        # 1. Role permissions (meta-driven)
        # -------------------------------
        curr_meta = DR_STEP_META.get(current_column, {})
        allowed_roles = curr_meta.get("forward_roles", set()) if is_forward else curr_meta.get("backward_roles", set())

        # Door-to-Door: Sales can move forward from DELIVERED (after approval) - preserve your existing rule
        if self.delivery_method == DeliveryMethod.DOOR_TO_DOOR and current_column == "DELIVERED" and is_forward:
            allowed_roles = {"SalesAgent", "SalesHead", "TopManagement"}

        if actor_role not in allowed_roles:
            raise PermissionDenied(f"Role {actor_role} not allowed to move from {current_column}")

        # -------------------------------
        # 2. Global CASH restrictions (preserve)
        # -------------------------------
        CASH_ALLOWED = {"NEW_DR", "FOR_DELIVERY", "DELIVERED", "FOR_DEPOSIT", "DEPOSITED"}
        if pm == "CASH" and target_column not in CASH_ALLOWED:
            raise ValidationError("Cash DRs cannot move into countering or collection steps.")

        # -------------------------------
        # 3. Forward movement adjacency (preserve, but lifecycle-aware)
        # -------------------------------
        if is_forward:
            # Door-to-Door special forward rule: NEW_DR -> DELIVERED directly
            if (
                self.delivery_method == DeliveryMethod.DOOR_TO_DOOR
                and current_column == "NEW_DR"
                and target_column == "DELIVERED"
            ):
                # Keep your exact behavior: set delivered + pending approval
                self.delivery_status = DeliveryStatus.DELIVERED
                self.payment_status = PaymentStatus.NA
                self.approval_status = ApprovalStatus.PENDING
                self.save(update_fields=["delivery_status", "payment_status", "approval_status"])

                msg = f"Door-to-Door moved from NEW_DR to DELIVERED by {actor_role}."
                if user_notes:
                    msg += f" Notes: {user_notes}"
                self.log_update(user=user, message=msg, user_notes=user_notes)
                return

            # Standard rule: must move to the next step only (adjacent)
            expected_next = lifecycle[current_idx + 1] if current_idx + 1 < len(lifecycle) else None

            # Cash branching at DELIVERED is already expressed by lifecycle_for(),
            # so expected_next already becomes FOR_DEPOSIT for cash, or FOR_COUNTER_CREATION for terms.
            if target_column != expected_next:
                raise ValidationError(f"Invalid forward move. Allowed: {expected_next or 'none'}")

            # Transition preconditions: required fields before forward
            required_fields = curr_meta.get("required_before_forward", [])
            missing = [f for f in required_fields if not getattr(self, f)]

            if missing:
                # Preserve your messages where it matters
                if current_column == "FOR_DELIVERY" and target_column == "DELIVERED" and "date_of_delivery" in missing:
                    raise ValidationError("Please set the Delivery Date first.")
                if current_column == "FOR_DEPOSIT" and target_column == "DEPOSITED" and "payment_details" in missing:
                    raise ValidationError("Payment details must be provided before marking as Deposited.")
                if current_column == "FOR_COUNTER_CREATION" and target_column == "FOR_COUNTERING" and "payment_due" in missing:
                    raise ValidationError("Payment Due must be filled before moving to Countered.")
                raise ValidationError(f"Missing required fields: {', '.join(missing)}")

        # -------------------------------
        # 4. Backward movement adjacency (preserve)
        # -------------------------------
        if is_backward:
            # Door-to-Door special backward rule: DELIVERED -> NEW_DR only
            if (
                self.delivery_method == DeliveryMethod.DOOR_TO_DOOR
                and current_column == "DELIVERED"
                and target_column == "NEW_DR"
            ):
                self.delivery_status = DeliveryStatus.NEW_DR
                self.payment_status = PaymentStatus.NA
                self.approval_status = ApprovalStatus.PENDING
                self.save(update_fields=["delivery_status", "payment_status", "approval_status"])

                msg = f"Door-to-Door reverted from DELIVERED to NEW DR by {actor_role}."
                if user_notes:
                    msg += f" Notes: {user_notes}"
                self.log_update(user=user, message=msg, user_notes=user_notes)
                return

            # CASH backward rules (exactly as your code)
            if pm == "CASH":
                # Superuser exception: DEPOSITED -> FOR_DEPOSIT
                if current_column == "DEPOSITED" and target_column == "FOR_DEPOSIT":
                    if not user.is_superuser:
                        raise ValidationError("Only superusers may move Cash DRs from Deposited to For Deposit.")
                else:
                    allowed_back = {
                        "FOR_DEPOSIT": ["DELIVERED"],
                        "DELIVERED": ["FOR_DELIVERY"],
                        "FOR_DELIVERY": ["NEW_DR"],
                    }
                    if target_column not in allowed_back.get(current_column, []):
                        raise ValidationError(f"Invalid backward move for Cash DRs: {current_column} → {target_column}")
            else:
                # TERMS backward: must move one step back in lifecycle
                if current_idx == 0:
                    raise ValidationError("Cannot move back from the first column.")
                expected_prev = lifecycle[current_idx - 1]
                if target_column != expected_prev:
                    raise ValidationError(f"You can only move back to {expected_prev}.")

        # -------------------------------
        # 5. Status mapping (meta-driven) + preserve your one special backward mapping
        # -------------------------------
        if is_backward and current_column == "FOR_COUNTER_CREATION" and target_column == "DELIVERED":
            # Preserve your special case: back to DELIVERED sets APPROVED
            self.delivery_status = DeliveryStatus.DELIVERED
            self.payment_status = PaymentStatus.NA
            self.approval_status = ApprovalStatus.APPROVED
        else:
            tmeta = DR_STEP_META.get(target_column)
            if not tmeta:
                raise ValidationError("Target column metadata missing.")

            smap = tmeta.get("status_map", {})
            if smap.get("delivery_status") is not None:
                self.delivery_status = smap["delivery_status"]
            if smap.get("payment_status") is not None:
                self.payment_status = smap["payment_status"]

            # Approval behavior on forward entry
            if is_forward:
                if tmeta.get("auto_approve_on_enter_forward"):
                    self.approval_status = ApprovalStatus.APPROVED
                elif tmeta.get("approval_on_enter_forward", True):
                    self.approval_status = ApprovalStatus.PENDING

            # If moving backward, keep your behavior: mark as is unless your old code changed it
            if is_backward:
                # your old code doesn’t force approval_status here except special cases above
                pass

        self.save()

        # -------------------------------
        # 6. Logging (preserve)
        # -------------------------------
        msg = f"Moved from {current_column} to {target_column} as {actor_role}."
        if user_notes:
            msg += f" Notes: {user_notes}"
        self.log_update(user=user, message=msg, user_notes=user_notes)

    # ====== Approval / Decline ======
    def approve_current_step(self, user, user_notes: str = "", simulated_role: str | None = None):
        if simulated_role and is_top_management(user):
            actor_role = simulated_role
        else:
            actor_role = get_user_role(user)

        if not actor_role:
            raise PermissionDenied("Your account does not have an assigned role.")

        if self.approval_status != ApprovalStatus.PENDING:
            raise ValidationError("This DR is not pending approval.")

        column = self.get_current_column()
        meta = DR_STEP_META.get(column, {})
        allowed = set(meta.get("approver_roles", set()))

        if actor_role not in allowed:
            raise PermissionDenied(f"Role {actor_role} is not allowed to approve in {column}.")

        self.approval_status = ApprovalStatus.APPROVED
        self.save(update_fields=["approval_status", "updated_at"])

        msg = f"Approved in column {column} as {actor_role}."
        if user_notes:
            msg += f" Notes: {user_notes}"
        self.log_update(user=user, message=msg, user_notes=user_notes)

    def decline_current_step(self, user, user_notes: str = "", simulated_role: str | None = None):
        if simulated_role and is_top_management(user):
            actor_role = simulated_role
        else:
            actor_role = get_user_role(user)

        if not actor_role:
            raise PermissionDenied("Your account does not have an assigned role.")

        if self.approval_status != ApprovalStatus.PENDING:
            raise ValidationError("This DR is not pending approval.")

        current_column = self.get_current_column()

        meta = DR_STEP_META.get(current_column, {})
        allowed = set(meta.get("decliner_roles", set()))

        if actor_role not in allowed:
            raise PermissionDenied(f"Role {actor_role} is not allowed to decline in {current_column}.")

        # Decline behaviour: preserve your Door-to-Door delivered decline shortcut
        if (
            self.delivery_method == DeliveryMethod.DOOR_TO_DOOR
            and self.delivery_status == DeliveryStatus.DELIVERED
        ):
            self.delivery_status = DeliveryStatus.NEW_DR
            self.payment_status = PaymentStatus.NA
            self.approval_status = ApprovalStatus.APPROVED
            self.save(update_fields=["delivery_status", "payment_status", "approval_status", "updated_at"])
            return

        if current_column == "NEW_DR":
            # Stay in NEW_DR but mark as DECLINED
            self.approval_status = ApprovalStatus.DECLINED
            self.save(update_fields=["approval_status", "updated_at"])

            msg = f"Declined in NEW_DR as {actor_role}. Returned to Sales Agent for editing."
            if user_notes:
                msg += f" Notes: {user_notes}"
            self.log_update(user=user, message=msg, user_notes=user_notes)
            return

        lifecycle = DeliveryReceipt.dr_lifecycle_for(self)
        if current_column not in lifecycle:
            raise ValidationError("Invalid current column for this DR type.")

        # Special case: cash DR declined in FOR_DEPOSIT goes back to DELIVERED (preserve)
        pm = str(self.payment_method).upper()
        if pm == "CASH" and current_column == "FOR_DEPOSIT":
            self.delivery_status = DeliveryStatus.DELIVERED
            self.payment_status = PaymentStatus.NA
            self.approval_status = ApprovalStatus.DECLINED
            self.save(update_fields=["delivery_status", "payment_status", "approval_status", "updated_at"])
            message = self.log_update(user, "Declined – moved back to Delivered (Cash rule)")
            return

        idx = lifecycle.index(current_column)
        if idx == 0:
            raise ValidationError("Cannot move back from the first column.")

        prev_column = lifecycle[idx - 1]

        # Apply prev_column mapping via meta
        pmeta = DR_STEP_META.get(prev_column)
        if not pmeta:
            raise ValidationError("Previous column metadata missing.")

        smap = pmeta.get("status_map", {})
        if smap.get("delivery_status") is not None:
            self.delivery_status = smap["delivery_status"]
        if smap.get("payment_status") is not None:
            self.payment_status = smap["payment_status"]

        self.approval_status = ApprovalStatus.DECLINED
        self.save(update_fields=["delivery_status", "payment_status", "approval_status", "updated_at"])

        msg = f"Declined in {current_column} as {actor_role}. Moved back to {prev_column} for clarification."
        if user_notes:
            msg += f" Notes: {user_notes}"
        message = self.log_update(user=user, message=msg, user_notes=user_notes)

    # ====== DR number helper ======
    def get_missing_required_before_forward(self):
        current_step = self.get_current_column()
        meta = DR_STEP_META.get(current_step, {})

        required_fields = meta.get("required_before_forward", [])
        missing = []

        for field in required_fields:
            value = getattr(self, field, None)
            if value in (None, "", []):
                missing.append(field)

        return missing


    @classmethod
    def get_next_dr_number(cls):
        year = 6202
        prefix = f"{year}-"
        last = (
            cls.objects
            .filter(dr_number__startswith=prefix)
            .order_by("-dr_number")
            .first()
        )
        if last:
            try:
                last_seq = int(last.dr_number.split("-")[1])
            except (IndexError, ValueError):
                last_seq = 0
        else:
            last_seq = 0
        next_seq = last_seq + 1
        return f"{year}-{next_seq:04d}"

    def save(self, *args, **kwargs):
        if not self.dr_number:
            self.dr_number = self.get_next_dr_number()

        # Auto-initialize Door-to-Door flow:
        if self.delivery_method == DeliveryMethod.DOOR_TO_DOOR and not self.pk:
            self.delivery_status = DeliveryStatus.NEW_DR
            self.payment_status = PaymentStatus.NA
            self.approval_status = ApprovalStatus.PENDING
       
        # Sample: force client + strip payment/invoice/deposit fields (always blank)
        if self.delivery_method == DeliveryMethod.SAMPLE:
            self.client = DeliveryReceipt.get_sample_client()
            self.payment_status = PaymentStatus.NA

            # Always blank these fields for Sample
            self.payment_due = None
            self.payment_details = ""
            self.sales_invoice_no = None
            self.deposit_slip_no = None

        if self.delivery_method == DeliveryMethod.D2D_STOCKS:
            self.client = DeliveryReceipt.get_d2d_stocks_client()
            self.approval_status = ApprovalStatus.APPROVED
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()

        # Door to Door must have a source DR and delivery date
        if self.delivery_method == DeliveryMethod.DOOR_TO_DOOR:
            if not self.source_dr_id:
                raise ValidationError({"source_dr": "Source DR is required for Door to Door."})
            if not self.date_of_delivery:
                raise ValidationError({"date_of_delivery": "Delivery Date is required for Door to Door."})

            # Source DR must be D2D Stocks and not archived
            if self.source_dr.delivery_method != DeliveryMethod.D2D_STOCKS:
                raise ValidationError({"source_dr": "Source DR must be an D2D Stocks DR."})
            if self.source_dr.is_archived:
                raise ValidationError({"source_dr": "Source DR is archived and cannot be used."})

        # D2D Stocks: should never participate in normal workflow moves (handled in move_to_column)
        # but we keep statuses default as you requested.
    @staticmethod
    def get_sample_client():
        from .models import Client

        client, _ = Client.objects.get_or_create(
            company_name="Sample",
            defaults={
                "street_number": "Internal",
                "street_name": "Internal",
                "barangay": "Internal",
                "province_state": "Internal",
                "city_municipality": "Internal",
                "postal_code": "Internal",
            },
        )
        return client

    @staticmethod
    def get_d2d_stocks_client():
        from .models import Client

        client, _ = Client.objects.get_or_create(
            company_name="D2D Stocks",
            defaults={
                "street_number": "Internal",
                "street_name": "Internal",
                "barangay": "Internal",
                "province_state": "Internal",
                "city_municipality": "Internal",
                "postal_code": "Internal",
            },
        )
        return client
    
    def get_current_and_next_step(self):
        steps = self.get_lifecycle_steps()
        current = self.get_current_column()

        if current not in steps:
            return current, None

        idx = steps.index(current)
        next_step = steps[idx + 1] if idx + 1 < len(steps) else None

        return current, next_step

    def get_lifecycle_steps(self):
        """
        Returns the ordered lifecycle steps for this DR
        based on delivery_method and payment_method.
        """
        # D2D Stocks: not a workflow
        if self.delivery_method == DeliveryMethod.D2D_STOCKS:
            return ["D2D_STOCKS"]

        pm = self.payment_method
        dm = self.delivery_method

        if dm == DeliveryMethod.SAMPLE:
            return ["NEW_DR", "FOR_DELIVERY", "DELIVERED"]
        # Door to Door + Cash
        if dm == DeliveryMethod.DOOR_TO_DOOR and pm == PaymentMethod.CASH:
            return [
                "NEW_DR",
                "DELIVERED",
                "FOR_DEPOSIT",
                "DEPOSITED",
            ]

        # Door to Door (terms)
        if dm == DeliveryMethod.DOOR_TO_DOOR:
            return [
                "NEW_DR",
                "DELIVERED",
                "FOR_COUNTER_CREATION",
                "FOR_COUNTERING",
                "COUNTERED",
                "FOR_COLLECTION",
                "FOR_DEPOSIT",
                "DEPOSITED",
            ]

        # Cash (standard delivery)
        if pm == PaymentMethod.CASH:
            return [
                "NEW_DR",
                "FOR_DELIVERY",
                "DELIVERED",
                "FOR_DEPOSIT",
                "DEPOSITED",
            ]

        # Standard DR (default)
        return [
            "NEW_DR",
            "FOR_DELIVERY",
            "DELIVERED",
            "FOR_COUNTER_CREATION",
            "FOR_COUNTERING",
            "COUNTERED",
            "FOR_COLLECTION",
            "FOR_DEPOSIT",
            "DEPOSITED",
        ]




class DeliveryReceiptItem(models.Model):
    delivery_receipt = models.ForeignKey(
        DeliveryReceipt,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="delivery_receipt_items",
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Defaults to product name; user can add more details.",
    )
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(
        max_digits=12, decimal_places=2, editable=False
    )

    def save(self, *args, **kwargs):
        if not self.description and self.product_id:
            self.description = self.product.name

        if self.quantity is not None and self.unit_price is not None:
            self.line_total = self.quantity * self.unit_price

        super().save(*args, **kwargs)

        if self.delivery_receipt_id:
            self.delivery_receipt.recalc_total_amount(save=True)

    def __str__(self):
        return f"{self.product} x {self.quantity} ({self.delivery_receipt.dr_number})"


class Counter(models.Model):
    counter_number = models.CharField(
        max_length=20,
        unique=True,
        help_text="Format: C-YYYY-XXXX (e.g., C-2025-0001).",
    )
    date_issued = models.DateField(default=timezone.now)
    to = models.CharField(
        max_length=255,
        help_text="Recipient name (usually client contact).",
    )
    address = models.TextField(
        help_text="Recipient address, usually the client address.",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.counter_number


class InventoryIssuance(models.Model):
    TF_TO_WH = "TF_TO_WH"
    WH_TO_HQ = "WH_TO_HQ"

    ISSUANCE_TYPE_CHOICES = [
        (TF_TO_WH, "TF → WH"),
        (WH_TO_HQ, "WH → HQ"),
    ]

    issuance_type = models.CharField(max_length=20, choices=ISSUANCE_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    is_pending = models.BooleanField(default=True)
    is_cancelled = models.BooleanField(default=False)

    remarks = models.TextField(blank=True)
    date = models.DateField(default=timezone.now)

    def __str__(self):
        return f"ISS-{self.id}"

class InventoryIssuanceItem(models.Model):
    issuance = models.ForeignKey(
        InventoryIssuance,
        related_name="items",
        on_delete=models.CASCADE
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()


class DeliveryReceiptUpdate(models.Model):
    delivery_receipt = models.ForeignKey(
        DeliveryReceipt,
        on_delete=models.CASCADE,
        related_name="updates",
    )
    timestamp = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="delivery_receipt_updates",
    )
    system_update = models.TextField(
        help_text="Auto-generated summary, e.g. "
                  "`[MM/DD/YYYY] User X changed payment_status from A to B`."
    )
    user_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Update for {self.delivery_receipt.dr_number} at {self.timestamp}"




    
# =========================
#  Purchase Order
# =========================


PO_META = {
    POStatus.REQUEST_FOR_PAYMENT: {
        "label": "Request for Payment",
        "forward_roles": {"AccountingOfficer", "RVT"},
        "approver_roles": set(),
        "decliner_roles": set(),
        "requires_approval": False,
        "on_approve": None,
    },

    POStatus.REQUEST_FOR_PAYMENT_APPROVAL: {
        "label": "Request for Payment Approval",
        "forward_roles": set(),
        "approver_roles": {"AccountingHead", "TopManagement"},
        "decliner_roles": {"RVT"},
        "requires_approval": True,
        "on_approve": POStatus.PURCHASE_ORDER,
    },

    POStatus.PURCHASE_ORDER: {
        "label": "Purchase Order",
        "forward_roles": {"AccountingOfficer", "RVT"},
        "approver_roles": set(),
        "decliner_roles": set(),
        "requires_approval": False,
        "on_approve": None,
    },

    POStatus.PURCHASE_ORDER_APPROVAL: {
        "label": "Purchase Order Approval",
        "forward_roles": set(),
        "approver_roles": {"TopManagement"},
        "decliner_roles": {"JGG"},
        "requires_approval": True,
        "on_approve": POStatus.BILLING,
        "side_effect": "generate_po_number",
    },

    POStatus.BILLING: {
        "label": "Billing",
        "forward_roles": {"RVT"},
        "approver_roles": set(),
        "decliner_roles": set(),
        "requires_approval": False,
        "gate": "billing_totals_match_and_paid",
    },

    POStatus.PO_FILING: {
        "label": "PO Filing",
        "forward_roles": {"RVT"},
        "approver_roles": {"AccountingOfficer", "AccountingHead", "TopManagement"},
        "decliner_roles": {"RVT"},
        "requires_approval": True,
        "on_approve": None,
    },

    POStatus.ARCHIVED: {
        "label": "Archived",
        "forward_roles": set(),
        "approver_roles": set(),
        "decliner_roles": set(),
        "requires_approval": False,
    },
}

class PurchaseOrder(models.Model):
    paid_to = models.CharField(max_length=255, help_text="Supplier name")
    address = models.TextField(help_text="Supplier address")
    date = models.DateField(default=timezone.now)

    status = models.CharField(
        max_length=30,
        choices=POStatus.choices,
        default=POStatus.REQUEST_FOR_PAYMENT,
    )

    approval_status = models.CharField(
        max_length=20,
        choices=POApprovalStatus.choices,
        default=POApprovalStatus.PENDING,
    )
    is_archived = models.BooleanField(default=False)
    is_cancelled = models.BooleanField(default=False)

    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    prepared_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="prepared_purchase_orders",
    )
    checked_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="checked_purchase_orders",
        null=True,
        blank=True,
        help_text="Usually Accounting Head",
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="approved_purchase_orders",
        null=True,
        blank=True,
        help_text="Usually Top Management",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    po_number = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
    )
    rfp_number = models.CharField(
        max_length=20,
        unique=True,
        blank=True,
        null=True,
    )
    product_id_ref = models.ForeignKey(
        ProductID,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_orders",
    )



    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PO #{self.id} - {self.paid_to}"

    def recalc_total(self, save=True):
        total = self.particulars.aggregate(sum=Sum("total_price"))["sum"] or 0
        self.total = total
        if save:
            self.save(update_fields=["total"])

    # -------------------------
    # PO Kanban helpers
    # -------------------------
    @staticmethod
    def resolve_actor_role(user, simulated_role=None):
        if user.is_superuser:
            # Superuser bypasses role restrictions
            return simulated_role or "SUPERUSER"

        if simulated_role:
            return simulated_role

        return get_user_role(user)

    
    def get_current_column(self) -> str:
        if self.is_archived or self.status == POStatus.ARCHIVED:
            return "ARCHIVED"
        return self.status

    def log_update(self, user, message: str, user_notes: str = ""):
        return PurchaseOrderUpdate.objects.create(
            purchase_order=self,
            user=user,
            system_update=message,
            user_notes=user_notes or "",
        )

    def prev_status(self):
        if self.status not in PO_COLUMN_INDEX:
            return None
        idx = PO_COLUMN_INDEX[self.status]
        return PO_FLOW[idx - 1] if idx > 0 else None

    def next_status(self):
        if self.status not in PO_COLUMN_INDEX:
            return None
        idx = PO_COLUMN_INDEX[self.status]
        return PO_FLOW[idx + 1] if idx < len(PO_FLOW) - 1 else None
    
    def submit_to_next(self, user, user_notes="", simulated_role=None):
        actor_role = self.resolve_actor_role(user, simulated_role)
        if not actor_role:
            raise PermissionDenied("No role.")

        if self.is_archived or self.status == POStatus.ARCHIVED:
            raise ValidationError("Archived POs cannot be submitted.")

        meta = PO_META.get(self.status)
        if not meta:
            raise ValidationError("Invalid PO state.")

        # Approval gate
        if meta.get("requires_approval") and self.approval_status != POApprovalStatus.APPROVED:
            raise ValidationError("This step must be approved before proceeding.")

        # Role gate
        if meta["forward_roles"] and actor_role not in meta["forward_roles"] and actor_role != "SUPERUSER":
            raise PermissionDenied("You cannot submit this step.")

        # Business gate (Billing)
        gate = meta.get("gate")
        if gate == "billing_totals_match_and_paid":
            ok, po_r, billed_r, reason = self.totals_match_and_paid()
            if not ok:
                raise ValidationError(
                    f"Cannot proceed to PO Filing. {reason} "
                    f"(PO Total ₱{po_r}, Billed ₱{billed_r})"
                )

        nxt = self.next_status()
        if not nxt:
            raise ValidationError("No next step.")

        self.status = nxt
        self.approval_status = POApprovalStatus.PENDING
        self.save(update_fields=["status", "approval_status", "updated_at"])

        self.log_update(user, f"Submitted forward to {nxt}.", user_notes)

    def approve_current_step(self, user, user_notes="", simulated_role=None):
        actor_role = self.resolve_actor_role(user, simulated_role)
        if not actor_role:
            raise PermissionDenied("No role.")

        if self.approval_status != POApprovalStatus.PENDING:
            raise ValidationError("Not pending approval.")

        meta = PO_META.get(self.status)
        if not meta:
            raise ValidationError("Invalid PO state.")

        if actor_role not in meta["approver_roles"] and actor_role != "SUPERUSER":
            raise PermissionDenied("Not allowed to approve this step.")

        # Side effects
        if meta.get("side_effect") == "generate_po_number":
            self.po_number = PurchaseOrder.get_next_po_number()

        next_status = meta.get("on_approve")
        if next_status:
            self.status = next_status

        self.approval_status = POApprovalStatus.APPROVED
        self.save(update_fields=["status", "po_number", "approval_status", "updated_at"])

        self.log_update(user, f"Approved in {meta['label']}.", user_notes)
    def decline_current_step(self, user, user_notes="", simulated_role=None):
        actor_role = self.resolve_actor_role(user, simulated_role)
        if not actor_role:
            raise PermissionDenied("No role.")

        meta = PO_META.get(self.status)
        if actor_role not in meta.get("decliner_roles", set()):
            raise PermissionDenied("Not allowed to decline.")

        if self.status == POStatus.REQUEST_FOR_PAYMENT_APPROVAL:
            self.log_update(user, "Declined at RFP Approval. PO deleted.", user_notes)
            self.delete()
            return

        prev = self.prev_status()
        self.status = prev
        self.approval_status = POApprovalStatus.DECLINED
        self.save(update_fields=["status", "approval_status", "updated_at"])

        self.log_update(user, f"Declined. Moved back to {prev}.", user_notes)

    @classmethod
    def get_next_po_number(cls):
        year = timezone.now().year
        prefix = f"PO-{year}-"

        last = (
            cls.objects
            .filter(po_number__startswith=prefix)
            .order_by("-po_number")
            .first()
        )

        if last and last.po_number:
            last_seq = int(last.po_number.split("-")[-1])
            next_seq = last_seq + 1
        else:
            next_seq = 1

        return f"{prefix}{next_seq:04d}"

    @classmethod
    def get_next_rfp_number(cls):
        year = timezone.now().year
        prefix = f"RFP-{year}-"

        last = (
            cls.objects
            .filter(rfp_number__startswith=prefix)
            .order_by("-rfp_number")
            .first()
        )

        if last and last.rfp_number:
            last_seq = int(last.rfp_number.split("-")[-1])
            next_seq = last_seq + 1
        else:
            next_seq = 1

        return f"{prefix}{next_seq:04d}"
        
    def billed_total(self):
        return self.billings.filter(is_cancelled=False).aggregate(sum=Sum("amount"))["sum"] or 0

    def balance_amount(self):
        return (self.total or 0) - self.billed_total()

    def totals_match_and_paid(self):
        """
        Option B rule:
        - billed total == particulars total (rounded)
        - AND all billings are PAID (excluding cancelled)
        """
        q = Decimal("0.01")
        po_total = Decimal(self.total or 0).quantize(q, rounding=ROUND_HALF_UP)
        billed = Decimal(self.billed_total() or 0).quantize(q, rounding=ROUND_HALF_UP)

        if po_total != billed:
            return False, po_total, billed, "Totals do not match."

        not_paid = self.billings.filter(is_cancelled=False).exclude(status=BillingStatus.PAID).exists()
        if not_paid:
            return False, po_total, billed, "Not all billings are PAID."

        return True, po_total, billed, ""


class PurchaseOrderParticular(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="particulars",
    )
    particular = models.CharField(max_length=500)
    quantity = models.PositiveIntegerField(null=True, blank=True)
    unit_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    total_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    def save(self, *args, **kwargs):
        if self.quantity is not None and self.unit_price is not None:
            self.total_price = self.quantity * self.unit_price
        super().save(*args, **kwargs)

        if self.purchase_order_id:
            self.purchase_order.recalc_total(save=True)

    def __str__(self):
        return f"{self.particular} ({self.purchase_order_id})"
class PurchaseOrderUpdate(models.Model):
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="updates",
    )
    timestamp = models.DateTimeField(default=timezone.now)
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="purchase_order_updates",
    )
    system_update = models.TextField()
    user_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"Update for PO #{self.purchase_order_id} at {self.timestamp}"

class BillingStatus(models.TextChoices):
    CHECK_CREATION = "CHECK_CREATION", "Check Creation"
    CHECK_SIGNING = "CHECK_SIGNING", "Check Signing"
    PAYMENT_RELEASE = "PAYMENT_RELEASE", "Payment Release"
    PAID = "PAID", "Paid"


class Billing(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)

    billing_number = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
    )

    source_po = models.ForeignKey(
        "PurchaseOrder",
        related_name="billings",
        on_delete=models.CASCADE,
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)

    cheque_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    status = models.CharField(
        max_length=30,
        choices=BillingStatus.choices,
        default=BillingStatus.CHECK_CREATION,
    )

    is_cancelled = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.billing_number:
            self.billing_number = Billing.get_next_billing_number()
        super().save(*args, **kwargs)

    @staticmethod
    def get_next_billing_number():
        year = timezone.now().year
        last = (
            Billing.objects
            .filter(billing_number__startswith=f"B-{year}")
            .order_by("-billing_number")
            .first()
        )
        next_seq = 1 if not last else int(last.billing_number.split("-")[-1]) + 1
        return f"B-{year}-{next_seq:04d}"
    
PO_CANCEL_ROLES = {"RVT"}

def can_cancel_po(user):
    role = get_user_role(user)
    return user.is_superuser or role in PO_CANCEL_ROLES

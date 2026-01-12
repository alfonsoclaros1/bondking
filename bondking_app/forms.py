from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator

from .models import (
    Client,
    InventoryIssuance,
    InventoryIssuanceItem,
    Product,
    DeliveryReceipt,
    DeliveryReceiptItem,
    PaymentMethod,
    DeliveryMethod,
    ProductID,
    get_user_role,
    is_top_management,
)

User = get_user_model()


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        rented = forms.ChoiceField(
            choices=[
                ("rented", "Rented"),
                ("owned", "Owned"),
            ],
            widget=forms.Select(attrs={"class": "form-select"}),
            required=True,
            label="Rented or Owned",
        )

        since = forms.CharField(
            required=False,
            widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. 2015"}),
            validators=[
                RegexValidator(
                    regex=r"^\d{4}$",
                    message="Enter a valid 4-digit year (e.g. 2015).",
                    code="invalid_year",
                )
            ]
        )

        def clean_rented(self):
            value = self.cleaned_data["rented"]
            return value == "rented"
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.fields["agent"].queryset = User.objects.filter(
                groups__name__in=["SalesAgent", "SalesHead"]
            ).distinct()
            self.fields["agent"].required = False

        fields = [
            "company_name",
            "name_of_owner",
            "agent",            
            "rented",
            "since",
            "contact_number",
            "unit_room",
            "street_number",
            "street_name",
            "barangay",
            "city_municipality",
            "province_state",
            "postal_code",
            "preferred_mop",
        ]


class DeliveryReceiptForm(forms.ModelForm):
    """
    DeliveryReceipt header form.
    Controls field editability based on stage AND role.
    """

    class Meta:
        model = DeliveryReceipt
        fields = [
            "date_of_order",
            "dr_number",
            "payment_method",
            "delivery_method",
            "source_dr",
            "agent",
            "client",
            "date_of_delivery",
            "payment_due",
            "payment_details",
            "payment_status",
            "proof_of_delivery",
            "sales_invoice_no", 
            "deposit_slip_no",      
            "remarks",
            "delivery_status",
            "payment_status",
        ]
        widgets = { 
            "date_of_order": forms.DateInput(attrs={"type": "date"}),
            "date_of_delivery": forms.DateInput(attrs={"type": "date"}),
            "payment_due": forms.DateInput(attrs={"type": "date"}),
            "sales_invoice_no": forms.TextInput(attrs={"class": "form-control"}),
            "deposit_slip_no": forms.TextInput(attrs={"class": "form-control"}),
            "delivery_status": forms.Select(attrs={"class": "form-select"}),
            "payment_status": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, stage=None, **kwargs):
        # Stage can come from the explicit argument or from kwargs (fallback)
        kw_stage = kwargs.pop("stage", None)
        self.stage = stage or kw_stage or "NEW_DR"

        self.user = user
        kwargs.pop("user", None)
        super().__init__(*args, **kwargs)


        # Default: lock these fields
        self.fields["delivery_status"].disabled = True
        self.fields["payment_status"].disabled = True

        # Top Management and AGR can edit
        if self.user and (
            is_top_management(self.user)
            or self.user.groups.filter(name="AGR").exists()
        ):
            self.fields["delivery_status"].disabled = False
            self.fields["payment_status"].disabled = False


        # Assign preview DR number if creating
        if not self.instance.pk:
            self.fields["dr_number"].initial = DeliveryReceipt.get_next_dr_number()
        self.fields["dr_number"].disabled = True

        # Required fields
        self.fields["date_of_order"].required = True
        self.fields["client"].required = True


        # D2D Stocks: client is forced and locked
        current_dm = None
        if self.instance and self.instance.pk:
            current_dm = self.instance.delivery_method
        else:
            current_dm = self.data.get("delivery_method")

        if current_dm == DeliveryMethod.D2D_STOCKS:
            self.fields["client"].disabled = True
        # Sample: client is forced and locked + payment/invoice/deposit fields locked
        if current_dm == DeliveryMethod.SAMPLE:
            self.fields["client"].disabled = True

            for fname in ["payment_due", "payment_details", "sales_invoice_no", "deposit_slip_no"]:
                if fname in self.fields:
                    self.fields[fname].disabled = True

        self.fields["payment_method"].required = True
        self.fields["delivery_method"].required = True
        self.fields["agent"].required = True

        # Optional fields
        self.fields["date_of_delivery"].required = False
        self.fields["payment_due"].required = False
        self.fields["payment_details"].required = False
        self.fields["remarks"].required = False
        self.fields["payment_status"].required = False
        self.fields["proof_of_delivery"].required = False
        self.fields["sales_invoice_no"].required = False
        self.fields["deposit_slip_no"].required = False

        # Make payment_details a small input instead of textarea
        self.fields["payment_details"].widget = forms.TextInput(attrs={"class": "form-control"})
        self.fields["proof_of_delivery"].widget = forms.ClearableFileInput(
            attrs={
                "class": "form-control",
                "accept": "image/*",
                "capture": "environment",  # 📸 opens camera on mobile
            }
        )

        # Source DR selection: only D2D Stocks DRs that are not archived
        if "source_dr" in self.fields:
            self.fields["source_dr"].queryset = (
                DeliveryReceipt.objects
                .filter(delivery_method=DeliveryMethod.D2D_STOCKS, is_archived=False)
                .order_by("-created_at")
            )
            self.fields["source_dr"].required = False
            
        # Conditionally show/require source_dr only for Door to Door
        current_dm = None
        if self.instance and self.instance.pk:
            current_dm = self.instance.delivery_method
        else:
            current_dm = (self.data.get("delivery_method") or self.initial.get("delivery_method"))

        # APPLY PERMISSIONS
        self._apply_stage_permissions(user=user)        
        if not self.instance.payment_status:
            self.initial["payment_status"] = "NA"
        # --- Door-to-Door: enable Source DR field ---
        if self.instance.pk and self.instance.is_cancelled:
            for field in self.fields.values():
                field.disabled = True

        
    def _apply_stage_permissions(self, user):
        """
        Control which fields are editable based on stage + role.

        Rules:
        1. NEW_DR – All is available except: date_of_delivery, payment_due, payment_details.
        2. FOR_DELIVERY, DELIVERED – date_of_delivery and payment_details only available
           if user is LogisticsOfficer / LogisticsHead / TopManagement.
        3. FOR_COUNTER_CREATION, COUNTERED, FOR_DEPOSIT – payment_due and payment_details
           available for AccountingOfficer / AccountingHead / TopManagement.
        4. FOR_COUNTERING, FOR_COLLECTION – payment_due and payment_details available for
           LogisticsOfficer / LogisticsHead / TopManagement.
        5. remarks is always editable.
        """

        role = get_user_role(user)
        stage = self.stage or "NEW_DR"

        logistics_roles = {"LogisticsOfficer", "LogisticsHead", "TopManagement"}
        accounting_roles = {"AccountingOfficer", "AccountingHead", "TopManagement"}

        # ------------------------------------------------------------
        # 0. Default: EVERYTHING disabled
        # ------------------------------------------------------------
        for field in self.fields.values():
            field.disabled = True

        # DR number is ALWAYS locked
        self.fields["dr_number"].disabled = True

        # ------------------------------------------------------------
        # 1. NEW_DR
        # ------------------------------------------------------------
        if stage == "NEW_DR":
            blocked = {
                "dr_number",
                "date_of_delivery",
                "payment_due",
                "payment_details",
                "proof_of_delivery",
                "sales_invoice_no",
                "deposit_slip_no",
            }

            for fname, field in self.fields.items():
                if fname not in blocked:
                    field.disabled = False

        # ------------------------------------------------------------
        # 2. FOR_DELIVERY / DELIVERED
        # ------------------------------------------------------------
        elif stage in ["FOR_DELIVERY", "DELIVERED"]:
            if role in logistics_roles or user.is_superuser or is_top_management(user):
                # Existing rules
                for fname in ["date_of_delivery", "payment_details"]:
                    if fname in self.fields:
                        self.fields[fname].disabled = False

                # ✅ NEW: Proof of Delivery ONLY in DELIVERED
                if stage == "DELIVERED":
                    self.fields["proof_of_delivery"].disabled = False
                    self.fields["sales_invoice_no"].disabled = False

        # ------------------------------------------------------------
        # 3. FOR_COUNTER_CREATION / COUNTERED
        # ------------------------------------------------------------
        elif stage in ["FOR_COUNTER_CREATION", "COUNTERED"]:
            if role in accounting_roles or user.is_superuser or is_top_management(user):
                for fname in ["payment_due", "payment_details"]:
                    if fname in self.fields:
                        self.fields[fname].disabled = False
                # ✅ NEW: Proof of Delivery ONLY in DELIVERED

        # ------------------------------------------------------------
        # 4. FOR_COUNTERING
        # ------------------------------------------------------------
        elif stage == "FOR_COUNTERING":
            if role in logistics_roles or user.is_superuser or is_top_management(user):
                for fname in ["payment_due", "payment_details", "sales_invoice_no"]:
                    if fname in self.fields:
                        self.fields[fname].disabled = False

        # ------------------------------------------------------------
        # 5. FOR_DEPOSIT
        # ------------------------------------------------------------
        elif stage == "FOR_DEPOSIT":
            if role in accounting_roles or user.is_superuser or is_top_management(user):
                for fname in ["payment_due", "payment_details"]:
                    if fname in self.fields:
                        self.fields[fname].disabled = False

                # ✅ NEW fields for this stage
                self.fields["sales_invoice_no"].disabled = False
                self.fields["deposit_slip_no"].disabled = False

        # ------------------------------------------------------------
        # 6. DEPOSITED → fully locked
        # ------------------------------------------------------------
        elif stage == "DEPOSITED":
            pass

        # ------------------------------------------------------------
        # 7. remarks ALWAYS editable
        # ------------------------------------------------------------
        self.fields["remarks"].disabled = False

        # ✅ FINAL OVERRIDE: Top Management + AGR can ALWAYS edit status fields
        if self.user and (
            self.user.is_superuser
            or is_top_management(self.user)
            or self.user.groups.filter(name="AGR").exists()
        ):
            self.fields["delivery_status"].disabled = False
            self.fields["payment_status"].disabled = False

                
    def clean_date_of_delivery(self):
        date = self.cleaned_data.get("date_of_delivery")
        stage = self.stage

        from datetime import date as dt

        today = dt.today()

        # Only apply restriction during FOR_DELIVERY stage
        if stage == "FOR_DELIVERY":
            if date:
                max_allowed = today.replace(day=today.day + 3)
                if date > max_allowed:
                    raise forms.ValidationError(
                        "Delivery Date must be within the next 3 days while the DR is in For Delivery."
                    )

        # In DELIVERED stage: no restriction
        return date
    def clean(self):
        cleaned = super().clean()

        # Default payment_status
        if not cleaned.get("payment_status"):
            cleaned["payment_status"] = "NA"

        # Sample: always blank payment/invoice/deposit fields
        dm = cleaned.get("delivery_method") or getattr(self.instance, "delivery_method", None)
        if dm == DeliveryMethod.SAMPLE:
            cleaned["payment_status"] = "NA"
            cleaned["payment_due"] = None
            cleaned["payment_details"] = ""
            cleaned["sales_invoice_no"] = None
            cleaned["deposit_slip_no"] = None

        return cleaned


class DeliveryReceiptItemForm(forms.ModelForm):
    class Meta:
        model = DeliveryReceiptItem
        fields = ["product", "description", "quantity", "unit_price"]

    def __init__(self, *args, **kwargs):
        self.stage = kwargs.pop("stage", "NEW_DR")
        super().__init__(*args, **kwargs)

        # ✅ DISPLAY SKU ONLY (not sku-description)
        self.fields["product"].label_from_instance = lambda obj: obj.sku
        # At creation stage, all item fields editable
        if self.stage != "NEW_DR":
            for name, field in self.fields.items():
                field.required = False  # Prevent validation errors
                if name == "product":
                    # 🔒 SKU dropdown → must use disabled
                    field.disabled = True
                else:
                    # 🔒 inputs (description, qty, price)
                    field.widget.attrs["readonly"] = True
                field.widget.attrs["tabindex"] = "-1"
                field.widget.attrs["style"] = "background:#f8f9fa;"

        self.fields["description"].widget.attrs["readonly"] = True



class BaseDeliveryReceiptItemFormSet(BaseInlineFormSet):
    """
    Custom formset to propagate `stage` into each form and control add/delete.
    """

    def __init__(self, *args, **kwargs):
        self.stage = kwargs.pop("stage", "NEW_DR")
        super().__init__(*args, **kwargs)

        # Disable add/delete at later stages if you want stricter control
        if self.stage != "NEW_DR":
            self.can_delete = False
            self.extra = 0

    def _construct_form(self, i, **kwargs):
        kwargs["stage"] = self.stage
        return super()._construct_form(i, **kwargs)


DeliveryReceiptItemFormSet = inlineformset_factory(
    DeliveryReceipt,
    DeliveryReceiptItem,
    form=DeliveryReceiptItemForm,
    formset=BaseDeliveryReceiptItemFormSet,
    fields=["product", "description", "quantity", "unit_price"],
    extra=5,
    can_delete=True,
)



from .models import PurchaseOrder, PurchaseOrderParticular, POStatus


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["rfp_number","product_id_ref", "paid_to", "address", "date", "po_number", "cheque_number"]
        widgets = {
            "paid_to": forms.TextInput(attrs={"class": "form-control"}),
            "address": forms.TextInput(attrs={"class": "form-control"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "po_number": forms.TextInput(attrs={
                "class": "form-control text-muted",
                "placeholder": "Generated upon PO Approval",
            }),
            "rfp_number": forms.TextInput(attrs={"class": "form-control text-muted",}),

            "cheque_number": forms.TextInput(attrs={"class": "form-control"}),

            "product_id_ref": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, user=None, stage=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user
        self.stage = stage or "REQUEST_FOR_PAYMENT"
        role = get_user_role(user) if user else None
        

        # -------------------------------------------------
        # 1. Default: lock EVERYTHING
        # -------------------------------------------------
        for field in self.fields.values():
            field.disabled = True


        # -------------------------------------------------
        # 2. Global rules (always apply)
        # -------------------------------------------------
        # PO number: system-generated, never editable
        self.fields["po_number"].disabled = True
        self.fields["po_number"].required = False
        self.fields["rfp_number"].disabled = True
        self.fields["rfp_number"].required = False
        self.fields["product_id_ref"].required = True

        # -------------------------------------------------
        # 3. Stage-based rules
        # -------------------------------------------------
        # REQUEST_FOR_PAYMENT
        if self.stage == "REQUEST_FOR_PAYMENT":
            if role in {"AccountingOfficer", "AccountingHead", "TopManagement"} or (user and user.is_superuser):
                for fname in ["paid_to", "address", "date"]:
                    self.fields[fname].disabled = False

        # CHECK_CREATION
        elif self.stage == "CHECK_CREATION":
            if role in {"AccountingOfficer", "AccountingHead", "TopManagement"} or (user and user.is_superuser):
                self.fields["cheque_number"].disabled = False
        # Cancelled PO: lock everything
        if self.instance.pk and self.instance.is_cancelled:
            for field in self.fields.values():
                field.disabled = True
            return


        if self.instance.pk:
            self.fields["product_id_ref"].disabled = True
        else:
            # allow selection on create
            self.fields["product_id_ref"].disabled = False

        if not self.instance.pk:
            self.fields["rfp_number"].initial = PurchaseOrder.get_next_rfp_number()

        if stage in ["REQUEST_FOR_PAYMENT_APPROVAL", "PURCHASE_ORDER_APPROVAL",
             "CHECK_SIGNING", "PO_FILING", "ARCHIVED"]:
            for field in self.fields.values():
                field.disabled = True



class PurchaseOrderParticularForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderParticular
        fields = ["particular", "quantity", "unit_price"]
        widgets = {
            "particular": forms.TextInput(attrs={
                "class": "form-control w-100",
            }),
            "quantity": forms.NumberInput(attrs={
                "class": "form-control text-end",
            }),
            "unit_price": forms.NumberInput(attrs={
                "class": "form-control text-end",
            }),
        }

    def __init__(self, *args, **kwargs):
        self.stage = kwargs.pop("stage", "REQUEST_FOR_PAYMENT")
        self.approval_status = kwargs.pop("approval_status", None)
        super().__init__(*args, **kwargs)

        editable = self.stage in {
            POStatus.REQUEST_FOR_PAYMENT,
            POStatus.PURCHASE_ORDER,
        }
        if not editable:
            for field in self.fields.values():
                field.required = False
                field.widget.attrs["readonly"] = True
                field.widget.attrs["tabindex"] = "-1"
                field.widget.attrs["style"] = "background:#f8f9fa;"


class BasePurchaseOrderParticularFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.stage = kwargs.pop("stage", "REQUEST_FOR_PAYMENT")
        self.approval_status = kwargs.pop("approval_status", None)
        super().__init__(*args, **kwargs)

        # Control add/delete only
        if not (
            self.stage == "REQUEST_FOR_PAYMENT"
            or (self.stage == "PURCHASE_ORDER" and self.approval_status == "PENDING")
        ):
            self.can_delete = False
            self.extra = 0

        # Control FIELD editability
        for form in self.forms:
            form.stage = self.stage
            form.approval_status = self.approval_status

            if not (
                self.stage == "REQUEST_FOR_PAYMENT"
                or (self.stage == "PURCHASE_ORDER" and self.approval_status == "PENDING")
            ):
                for field in form.fields.values():
                    field.required = False
                    field.widget.attrs["readonly"] = True
                    field.widget.attrs["tabindex"] = "-1"
                    field.widget.attrs["style"] = "background:#f8f9fa;"
    def _construct_form(self, i, **kwargs):
        kwargs["stage"] = self.stage
        kwargs["approval_status"] = self.approval_status
        return super()._construct_form(i, **kwargs)




PurchaseOrderParticularFormSet = inlineformset_factory(
    PurchaseOrder,
    PurchaseOrderParticular,
    form=PurchaseOrderParticularForm,
    formset=BasePurchaseOrderParticularFormSet,
    fields=["particular", "quantity", "unit_price"],
    extra=5,
    can_delete=True,
)



class InventoryIssuanceForm(forms.ModelForm):
    class Meta:
        model = InventoryIssuance
        fields = ["date", "issuance_type", "remarks"]
        widgets = {
            "issuance_type": forms.Select(
                attrs={
                    "class": "form-select form-select-sm",
                }
            ),

            "date": forms.DateInput(attrs={
                "type": "date",
                "class": "form-control form-control-sm"
                }
            ),

            "remarks": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm",
                    "rows": 2,
                    "placeholder": "Optional notes about this issuance",
                }
            ),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk and not self.instance.is_pending:
            for name, field in self.fields.items():
                # 🔒 Lock everything EXCEPT remarks
                if name != "remarks":
                    field.disabled = True

        # ✅ FINAL OVERRIDE: remarks is ALWAYS editable
        self.fields["remarks"].disabled = False



    def clean(self):
        cleaned_data = super().clean()
        issuance_type = cleaned_data.get("issuance_type")

        if issuance_type not in [
            InventoryIssuance.TF_TO_WH,
            InventoryIssuance.WH_TO_HQ,
        ]:
            raise forms.ValidationError("Invalid issuance type.")

        return cleaned_data

class InventoryIssuanceItemForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.is_locked = kwargs.pop("is_locked", False)
        super().__init__(*args, **kwargs)

        if self.is_locked:
            for field in self.fields.values():
                field.disabled = True

    class Meta:
        model = InventoryIssuanceItem
        fields = ["product", "quantity"]
        widgets = {
            "product": forms.Select(
                attrs={"class": "form-select form-select-sm"}
            ),
            "quantity": forms.NumberInput(
                attrs={
                    "class": "form-control form-control-sm text-end",
                    "min": 1,
                }
            ),
        }

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity")
        if qty is None or qty <= 0:
            raise forms.ValidationError("Quantity must be greater than zero.")
        return qty

    
InventoryIssuanceItemFormSet = inlineformset_factory(
    parent_model=InventoryIssuance,
    model=InventoryIssuanceItem,
    form=InventoryIssuanceItemForm,
    extra=1,
    can_delete=True,
)


from django.contrib import admin
from .models import *

admin.site.register(Client)
admin.site.register(Product)
admin.site.register(ProductID)

admin.site.register(DeliveryReceipt)
admin.site.register(DeliveryReceiptItem)

admin.site.register(InventoryIssuance)
admin.site.register(InventoryIssuanceItem)

admin.site.register(PurchaseOrder)
admin.site.register(PurchaseOrderParticular)
admin.site.register(Billing)

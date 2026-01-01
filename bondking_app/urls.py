from django.urls import path
from . import views
from django.contrib.auth import views as auth_views


urlpatterns = [
    #home redirect
    path("", views.root_redirect, name="root"),
    #auth
    path("login/", auth_views.LoginView.as_view(template_name="bondking_app/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password-reset/", auth_views.PasswordResetView.as_view(), name="password_reset"),
    path("password-reset/done/", auth_views.PasswordResetDoneView.as_view(), name="password_reset_done"),
    path("reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("reset/done/", auth_views.PasswordResetCompleteView.as_view(), name="password_reset_complete"),


    # DR Kanban actions
    path("dr/<int:pk>/move/", views.move_dr, name="dr-move"),

    # DR CRUD (examples)
    path("dr/new/", views.dr_create, name="dr-create"),
    path("dr/<int:pk>/", views.dr_detail, name="dr-detail"),
    path("kanban/", views.dr_kanban, name="dr-kanban"),
    path("dr/<int:pk>/print/", views.dr_print, name="dr-print"),


    # Client quick add
    path("clients/new/", views.client_create, name="client-create"),
    path("api/clients/<int:pk>/", views.client_detail_api, name="client-detail-api"),
    path("api/products/<int:pk>/", views.product_detail_api, name="product-detail-api"),
    path("dr/<int:pk>/approve/", views.dr_approve, name="dr-approve"),
    path("dr/<int:pk>/decline/", views.dr_decline, name="dr-decline"),
    path("dr/<int:pk>/edit/", views.dr_edit, name="dr-edit"),  
    path("dr/<int:dr_id>/archive/", views.archive_dr, name="dr-archive"),
    path("dr/<int:pk>/d2d-transactions/", views.d2d_transactions_api, name="dr-d2d-transactions"),
    path("dr/table/", views.dr_table, name="dr-table"),
    path("api/dr/<int:pk>/items/", views.dr_items_api, name="dr-items-api"),
    path("dr/table/export/", views.dr_table_export, name="dr-table-export"),
    path("dr/<int:pk>/cancel/", views.cancel_dr, name="dr-cancel"),


    # PO
    path("po/new/", views.po_create, name="po-create"),
    path("po/<int:pk>/edit/", views.po_edit, name="po-edit"),
    path("po/<int:pk>/submit/", views.po_submit, name="po-submit"),
    path("po/<int:pk>/complete/", views.po_complete, name="po-complete"),
    path("po/<int:pk>/submit/", views.po_submit, name="po-submit"),
    path("po/<int:pk>/approve/", views.po_approve, name="po-approve"),
    path("po/<int:pk>/decline/", views.po_decline, name="po-decline"),
    path("po/<int:pk>/archive/", views.archive_po, name="po-archive"),
    path("po/table/", views.po_table, name="po-table"),
    path("po/table/export/", views.po_table_export, name="po-table-export"),
    path("po/<int:pk>/cancel/", views.cancel_po, name="po-cancel"),
    path("product-ids/quick-create/",views.product_id_quick_create,name="product-id-quick-create",),
    path("po/<int:pk>/print/", views.po_print, name="po-print"),

    
    # Inventory
    path("inventory/table/", views.inventory_table, name="inventory-table"),
    path("inventory/<int:pk>/approve/", views.inventory_approve, name="inventory-approve"),
    path("inventory/<int:pk>/decline/", views.inventory_decline, name="inventory-decline"),
    path("inventory/new/", views.inventory_new, name="inventory-new"),
    path("inventory/<int:pk>/", views.inventory_edit, name="inventory-edit"),



]

from app.models.domain import InvoiceType, PartyType

INVOICE_TYPE_SELL = InvoiceType.SELL
INVOICE_TYPE_PURCHASE = InvoiceType.PURCHASE
INVOICE_TYPE_SELL_RETURN = InvoiceType.SELL_RETURN
INVOICE_TYPE_PURCHASE_RETURN = InvoiceType.PURCHASE_RETURN

PARTY_TYPE_CLIENT = PartyType.CLIENT
PARTY_TYPE_SUPPLIER = PartyType.SUPPLIER

STATUS_PAID = "paid"
STATUS_PARTIAL = "partial"
STATUS_UNPAID = "unpaid"

ZERO = "0"
ERR_PARTY_NOT_FOUND = "Party not found"
ERR_PRODUCT_NOT_FOUND = "Product not found"
ERR_INVOICE_NOT_FOUND = "Invoice not found"
ERR_BATCH_NOT_FOUND = "Batch not found"
ERR_PAYMENT_NOT_FOUND = "Payment not found"
ERR_INSUFFICIENT_STOCK = "Insufficient stock"
ERR_NO_VALID_RETURN_ITEMS = "No valid return items"
ERR_RETURN_QTY_EXCEEDS = "Return quantity exceeds original"
ERR_CANNOT_DELETE_HAS_STOCK = "لا يمكن الحذف لأن بعض البضاعة قد تم التصرف فيها."
ERR_CANNOT_DELETE_HAS_INVOICES = "لا يمكن حذف الطرف لوجود فواتير او دفعات"
ERR_CANNOT_MODIFY_RETURN = "لا يمكن تعديل بنود هذا النوع من الفواتير."
ERR_CANNOT_MODIFY_PURCHASE_COUNT = "لا يمكن إضافة أو حذف بنود من فاتورة الشراء، فقط تعديل الكميات والأسعار."
ERR_INVALID_INVOICE_TYPE = "Invalid invoice type"
ERR_INVALID_ITEM = "Invalid item"
ERR_CANNOT_DELETE_PRODUCT_HAS_STOCK = "لا يمكن حذف المنتج لوجود مخزون"

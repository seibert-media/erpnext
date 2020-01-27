import frappe
import json
from six import iteritems
from frappe.model.naming import make_autoname

def execute():
	if "tax_type" not in frappe.db.get_table_columns("Item Tax"):
		return
	old_item_taxes = {}
	item_tax_templates = {}

	frappe.reload_doc("accounts", "doctype", "item_tax_template_detail", force=1)
	frappe.reload_doc("accounts", "doctype", "item_tax_template", force=1)
	existing_templates = frappe.db.sql("""select template.name, details.tax_type, details.tax_rate
		from `tabItem Tax Template` template, `tabItem Tax Template Detail` details
		where details.parent=template.name
		""", as_dict=1)

	if len(existing_templates):
		for d in existing_templates:
			item_tax_templates.setdefault(d.name, {})
			item_tax_templates[d.name][d.tax_type] = d.tax_rate

	for d in frappe.db.sql("""select parent as item_code, tax_type, tax_rate from `tabItem Tax`""", as_dict=1):
		old_item_taxes.setdefault(d.item_code, [])
		old_item_taxes[d.item_code].append(d)

	frappe.reload_doc("stock", "doctype", "item", force=1)
	frappe.reload_doc("stock", "doctype", "item_tax", force=1)
	frappe.reload_doc("selling", "doctype", "quotation_item", force=1)
	frappe.reload_doc("selling", "doctype", "sales_order_item", force=1)
	frappe.reload_doc("stock", "doctype", "delivery_note_item", force=1)
	frappe.reload_doc("accounts", "doctype", "sales_invoice_item", force=1)
	frappe.reload_doc("buying", "doctype", "supplier_quotation_item", force=1)
	frappe.reload_doc("buying", "doctype", "purchase_order_item", force=1)
	frappe.reload_doc("stock", "doctype", "purchase_receipt_item", force=1)
	frappe.reload_doc("accounts", "doctype", "purchase_invoice_item", force=1)
	frappe.reload_doc("accounts", "doctype", "accounts_settings", force=1)

	frappe.db.auto_commit_on_many_writes = True

	# for each item that have item tax rates
	for item_code in old_item_taxes.keys():
		# make current item's tax map
		item_tax_map = {}
		for d in old_item_taxes[item_code]:
			item_tax_map[d.tax_type] = d.tax_rate

		item_tax_template_name = get_item_tax_template(item_tax_templates, item_tax_map, item_code)

		# update the item tax table
		item = frappe.get_doc("Item", item_code)
		item.set("taxes", [])
		item.append("taxes", {"item_tax_template": item_tax_template_name, "tax_category": ""})
		frappe.db.sql("delete from `tabItem Tax` where parent=%s and parenttype='Item'", item_code)
		for d in item.taxes:
			d.db_insert()

	doctypes = [
		'Quotation', 'Sales Order', 'Delivery Note', 'Sales Invoice',
		'Supplier Quotation', 'Purchase Order', 'Purchase Receipt', 'Purchase Invoice'
	]
	
	for dt in doctypes:
		for d in frappe.db.sql("""select name, parent, item_code, item_tax_rate from `tab{0} Item`
								where ifnull(item_tax_rate, '') not in ('', '{{}}') 
								and item_tax_template is NULL""".format(dt), as_dict=1):
			item_tax_map = json.loads(d.item_tax_rate)
			item_tax_template_name = get_item_tax_template(item_tax_templates,
				item_tax_map, d.item_code, d.parent)
			frappe.db.set_value(dt + " Item", d.name, "item_tax_template", item_tax_template_name)

	frappe.db.auto_commit_on_many_writes = False

	settings = frappe.get_single("Accounts Settings")
	settings.add_taxes_from_item_tax_template = 0
	settings.determine_address_tax_category_from = "Billing Address"
	settings.save()

def get_item_tax_template(item_tax_templates, item_tax_map, item_code, parent=None):
	# search for previously created item tax template by comparing tax maps
	for template, item_tax_template_map in iteritems(item_tax_templates):
		if item_tax_map == item_tax_template_map:
			return template

	# if no item tax template found, create one
	item_tax_template = frappe.new_doc("Item Tax Template")
	item_tax_template.title = make_autoname("Item Tax Template-.####")

	for tax_type, tax_rate in iteritems(item_tax_map):
		if not frappe.db.exists("Account", tax_type):
			parts = tax_type.strip().split(" - ")
			account_name = " - ".join(parts[:-1])
			company = frappe.db.get_value("Company", filters={"abbr": parts[-1]})
			parent_account = frappe.db.get_value("Account",
				filters={"account_type": "Tax", "root_type": "Liability", "is_group": 0, "company": company}, fieldname="parent_account")

			frappe.get_doc({
				"doctype": "Account",
				"account_name": account_name,
				"company": company,
				"account_type": "Tax",
				"parent_account": parent_account
			}).insert()

		item_tax_template.append("taxes", {"tax_type": tax_type, "tax_rate": tax_rate})
		item_tax_templates.setdefault(item_tax_template.title, {})
		item_tax_templates[item_tax_template.title][tax_type] = tax_rate
	item_tax_template.save()
	return item_tax_template.name

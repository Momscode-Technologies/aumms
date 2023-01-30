import frappe
from frappe.utils import *
from frappe import _

@frappe.whitelist()
def get_board_rate(item_type, purity, stock_uom, date, time):
    ''' Method to get Board Rate '''

    # add filters to get board rate
    filters = { 'docstatus': '1', 'item_type': item_type, 'purity': purity, 'date': getdate(date), 'time': ['<=', time]}

    if frappe.db.exists('Board Rate', filters):
        # get board rate and board rate uom (bruom)
        board_rate, bruom = frappe.db.get_value('Board Rate', filters, ['board_rate', 'uom'])
        # return board rate if board rate uom is same as stock uom
        if bruom == stock_uom:
            return board_rate
        # else multiply the board rate with conversion factor
        else:
            # get conversion factor value using stock_uom as from_uom and bruom as to_uom
            conversion_factor = get_conversion_factor(stock_uom, bruom)
            if conversion_factor:
                board_rate *= conversion_factor
                return board_rate
            else:
                # message to user about set conversion factor value
                frappe.throw(
                    _('Please set Conversion Factor for {0} {1}'.format(stock_uom, bruom))
                )
    else:
        # message to user about set Today's Board Rate value
        frappe.throw(
            _("Today's Board Rate is not updated for {0} {1}".format(purity, item_type))
        )

@frappe.whitelist()
def get_conversion_factor(from_uom, to_uom):
    """
        method to get conversion factor value using from uom and to uom
        output:
            return conversion factor value if exists else None
    """
    filters = {'from_uom': from_uom, 'to_uom': to_uom}
    return frappe.db.get_value('UOM Conversion Factor', filters, 'value')

@frappe.whitelist()
def create_metal_ledger_entries(doc, method=None):
    """
        method to create metal ledger entries
        args:
            doc: object of purchase Receipt doctype and Sales Invoice doctype
            method: on submit of purchase reciept and Sales Invoice
        output:
            new metal ledger entry doc
    """

    # get default company
    company = frappe.defaults.get_defaults().company

    # set dict of fields for metal ledger entry
    fields = {
        'doctype': 'Metal Ledger Entry',
        'posting_date': doc.posting_date,
        'posting_time': doc.posting_time,
        'voucher_type': doc.doctype,
        'voucher_no': doc.name,
        'company': company,
        'party_link': doc.party_link
    }

    # set party type and party in fields if doctype is Purchase Receipt
    if doc.doctype == 'Purchase Receipt':
        fields['party_type'] = 'Supplier'
        fields['party'] = doc.supplier

    # set party type and party in fields if doctype is Sales Invoice
    if doc.doctype == 'Sales Invoice':
        fields['party_type'] = 'Customer'
        fields['party'] = doc.customer

    # check items is keep_metal_ledger
    if doc.keep_metal_ledger:
        # declare ledger_created as false
        ledger_created = 0
        for item in doc.items:

                # set item details in fields
                fields['item_code'] = item.item_code
                fields['item_name'] = item.item_name
                fields['stock_uom'] = item.stock_uom
                fields['purity'] = item.purity
                fields['purity_percentage'] = item.purity_percentage
                fields['board_rate'] = item.rate
                fields['batch_no'] = item.batch_no
                fields['item_type'] = item.item_type
                fields['amount'] = -item.amount
                # get balance qty of the item for this party
                filters = {
                    'item_type': item.item_type,
                    'purity': item.purity,
                    'stock_uom': item.stock_uom,
                    'party_link': doc.party_link
                    }
                balance_qty = frappe.db.get_value('Metal Ledger Entry', filters, 'balance_qty')

                if doc.doctype == 'Purchase Receipt':
                    # update balance_qty
                    balance_qty = balance_qty+item.stock_qty if balance_qty else item.stock_qty
                    fields['in_qty'] = item.stock_qty
                    fields['outgoing_rate'] = item.rate
                    fields['balance_qty'] = balance_qty

                if doc.doctype == 'Sales Invoice':
                    # update balance_qty
                    balance_qty = balance_qty-item.stock_qty if balance_qty else -item.stock_qty
                    fields['incoming_rate'] = item.rate
                    fields['out_qty'] = item.stock_qty
                    fields['balance_qty'] = balance_qty

                # create metal ledger entry doc with fields
                frappe.get_doc(fields).insert(ignore_permissions = 1)
                ledger_created = 1

        # alert message if metal ledger is created
        if ledger_created:
            frappe.msgprint(
                msg = _(
                    'Metal Ledger Entry is created.'
                ),
                alert = 1
            )

@frappe.whitelist()
def cancel_metal_ledger_entries(doc, method=None):
    """
        method to cancel metal ledger entries of this voucher and create new entries
        args:
            doc: object of purchase receipt and Sales Invoice
            method: on cancel of purchase receipt and Sales Invoice
    """
    # get all Metal Ledger Entry linked with this doctype
    ml_entries = frappe.db.get_all('Metal Ledger Entry', {
        'voucher_type': doc.doctype,
        'voucher_no': doc.name
        })

    for ml in ml_entries:
        # get doc of metal ledger entry
        ml_doc = frappe.get_doc('Metal Ledger Entry', ml.name)
        # change is_cancelled value from 0 to 1
        ml_doc.is_cancelled = 1
        # ignoring this doctype from linked metal ledger doc
        ml_doc.ignore_linked_doctypes = (doc.doctype)
        # ignoring the links with this doctype
        ml_doc.flags.ignore_links = 1
        ml_doc.save(ignore_permissions = 1)

        # creating new document of metal ledger entry
        ml_doc.qty = -ml_doc.qty # updating value of qty as minus of existing qty

        # changing outgoing rate to incoming rate
        ml_doc.incoming_rate = ml_doc.outgoing_rate
        ml_doc.outgoing_rate = 0

        ml_doc.amount = -ml_doc.amount # updating amount value to minus of existing amount
        # insert new metal ledger entry doc
        ml_doc.insert(ignore_permissions = 1)

@frappe.whitelist()
def enable_common_party_accounting():
    """
        method to enable common party accounting on Accounts Settings after install
    """
    if frappe.db.exists('Accounts Settings'):
        accounts_settings_doc = frappe.get_doc('Accounts Settings')
        #set enable_common_party_accounting value as 1
        accounts_settings_doc.enable_common_party_accounting = 1
        accounts_settings_doc.save()
        frappe.db.commit()

@frappe.whitelist()
def validate_party_for_metal_transaction(doc, method=None):
    """
        method to validate party link if the transaction is metal transaction
        args:
            doc: object instance of the sales invoice/ purchase receipt document
    """
    # check_party_link_exist if doctype is Purchase Receipt
    if doc.doctype == 'Purchase Receipt':
        if doc.keep_metal_ledger:
            # check supplier is linked
            party_link = check_party_link_exist(
                "(primary_role = 'Supplier' AND primary_party = '{0}')".format(doc.supplier),
                "(secondary_role = 'Supplier' AND secondary_party = '{0}')".format(doc.supplier),
                doc.supplier
            )
            doc.party_link = party_link

    # check_party_link_exist if doctype is Sales Invoice
    if doc.doctype == 'Sales Invoice':
        if doc.keep_metal_ledger:
            # check customer is linked
            party_link =  check_party_link_exist(
                "(primary_role = 'Customer' AND primary_party = '{0}')".format(doc.customer),
                "(secondary_role = 'Customer' AND secondary_party = '{0}')".format(doc.customer),
                doc.customer
            )
            doc.party_link = party_link


def check_party_link_exist(filters, or_filters, party):
    """
        function to check party link exist for party and throw a message if not exists
        args:
            filters, or_filters = conditions used in sql query
            party : name of customer/ supplier
        output:
            party link or message to the user if the party is not linked
    """
    query = """
        SELECT
            name
        FROM
            `tabParty Link`
        WHERE
            {0} OR {1}
    """.format(filters, or_filters)
    party_link = frappe.db.sql(query, as_dict = 1)

    if not party_link:
        # message to the user if party link is not set
        frappe.throw(
            _("{0} doesn't have a common party account to conduct metal transaction".format(party))
            )
    else:
        return party_link[0].name

@frappe.whitelist()
def increase_precision():
    ''' Method to increase precision on System Settings after migrate '''
    if frappe.db.exists('System Settings'):
        system_settings_doc = frappe.get_doc('System Settings')
        system_settings_doc.float_precision = 6
        system_settings_doc.save()
        frappe.db.commit()

from datetime import date, datetime, timedelta
from json import loads

from accountancy.helpers import sort_multiple
from accountancy.testing.helpers import *
from cashbook.models import CashBook, CashBookTransaction
from controls.models import FinancialYear, ModuleSettings, Period
from django.contrib.auth import get_user_model
from django.shortcuts import reverse
from django.test import RequestFactory, TestCase
from django.utils import timezone
from nominals.models import Nominal, NominalTransaction
from sales.helpers import (create_credit_note_with_lines,
                           create_credit_note_with_nom_entries,
                           create_invoice_with_lines,
                           create_invoice_with_nom_entries, create_invoices,
                           create_lines, create_receipt_with_nom_entries,
                           create_receipts, create_refund_with_nom_entries,
                           create_vat_transactions)
from sales.models import Customer, SaleHeader, SaleLine, SaleMatching
from vat.models import Vat, VatTransaction

HEADER_FORM_PREFIX = "header"
LINE_FORM_PREFIX = "line"
match_form_prefix = "match"
SL_MODULE = "SL"
DATE_INPUT_FORMAT = '%d-%m-%Y'
MODEL_DATE_INPUT_FORMAT = '%Y-%m-%d'

def match(match_by, matched_to):
    headers_to_update = []
    matches = []
    match_total = 0
    for match_to, match_value in matched_to:
        match_total += match_value
        match_to.due = match_to.due - match_value
        match_to.paid = match_to.total - match_to.due
        matches.append(
            SaleMatching(
                matched_by=match_by,
                matched_to=match_to,
                value=match_value,
                period=match_by.period
            )
        )
        headers_to_update.append(match_to)
    match_by.due = match_by.total + match_total
    match_by.paid = match_by.total - match_by.due
    SaleHeader.objects.bulk_update(
        headers_to_update + [match_by], ['due', 'paid'])
    SaleMatching.objects.bulk_create(matches)
    return match_by, headers_to_update


def create_cancelling_headers(n, customer, ref_prefix, type, value, period):
    """
    Create n headers which cancel out with total = value
    Where n is an even number
    """
    date = timezone.now()
    due_date = date + timedelta(days=31)
    headers = []
    n = int(n / 2)
    for i in range(n):
        i = SaleHeader(
            customer=customer,
            ref=ref_prefix + str(i),
            goods=value,
            discount=0,
            vat=0,
            total=value,
            paid=0,
            due=value,
            date=date,
            due_date=due_date,
            type=type,
            period=period
        )
        headers.append(i)
    for i in range(n):
        i = SaleHeader(
            customer=customer,
            ref=ref_prefix + str(i),
            goods=value * -1,
            discount=0,
            vat=0,
            total=value * -1,
            paid=0,
            due=value * -1,
            date=date,
            due_date=due_date,
            type=type,
            period=period
        )
        headers.append(i)
    return SaleHeader.objects.bulk_create(headers)


class CreateInvoiceNominalEntries(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="dummy", password="dummy")
        cls.factory = RequestFactory()
        cls.customer = Customer.objects.create(name="test_customer")
        cls.ref = "test matching"
        cls.date = datetime.now().strftime(DATE_INPUT_FORMAT)
        cls.due_date = (datetime.now() + timedelta(days=31)).strftime(DATE_INPUT_FORMAT)
        cls.model_date = datetime.now().strftime(MODEL_DATE_INPUT_FORMAT)
        cls.model_due_date = (datetime.now() + timedelta(days=31)).strftime(MODEL_DATE_INPUT_FORMAT)
        fy = FinancialYear.objects.create(financial_year=2020)
        cls.fy = fy
        cls.period = Period.objects.create(fy=fy, period="01", fy_and_period="202001", month_start=date(2020,1,31))
        cls.description = "a line description"
        # ASSETS
        assets = Nominal.objects.create(name="Assets")
        current_assets = Nominal.objects.create(
            parent=assets, name="Current Assets")
        cls.nominal = Nominal.objects.create(
            parent=current_assets, name="Bank Account")
        cls.sale_control = Nominal.objects.create(
            parent=current_assets, name="Sales Ledger Control"
        )
        # LIABILITIES
        liabilities = Nominal.objects.create(name="Liabilities")
        current_liabilities = Nominal.objects.create(
            parent=liabilities, name="Current Liabilities")
        cls.vat_nominal = Nominal.objects.create(
            parent=current_liabilities, name="Vat")
        cls.vat_code = Vat.objects.create(
            code="1", name="standard rate", rate=20)
        cls.url = reverse("sales:create")
        ModuleSettings.objects.create(
            cash_book_period=cls.period,
            nominals_period=cls.period,
            purchases_period=cls.period,
            sales_period=cls.period
        )


    # CORRECT USAGE
    # Each line has a goods value above zero and the vat is 20% of the goods
    def test_nominals_created_for_lines_with_goods_and_vat_above_zero(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        matching_data = create_formset_data(match_form_prefix, [])
        line_forms = ([{

            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)
        header = headers[0]
        self.assertEqual(
            header.total,
            20 * (100 + 20)
        )
        self.assertEqual(
            header.goods,
            20 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                100 + 20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # CORRECT USAGE
    # Each line has a goods value above zero
    # And the vat is a zero value
    # We are only testing here that no nominal transactions for zero are created
    # We are not concerned about the vat return at all
    def test_nominals_created_for_lines_with_goods_above_zero_and_vat_equal_to_zero(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        matching_data = create_formset_data(match_form_prefix, [])
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 0
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)
        header = headers[0]
        self.assertEqual(
            header.total,
            20 * (100 + 0)
        )
        self.assertEqual(
            header.goods,
            20 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 0
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                0
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(2 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                None
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(2 * i) + 1]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        # assuming the lines are created in the same order
        # as the nominal entries....
        goods_trans = nom_trans[::2]
        total_trans = nom_trans[1::2]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # CORRECT USAGE
    # VAT only invoice
    # I.e. goods = 0 and vat = 20 on each analysis line
    def test_vat_only_lines_invoice(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        matching_data = create_formset_data(match_form_prefix, [])
        line_forms = ([{
            'description': self.description,
            'goods': 0,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)
        header = headers[0]
        self.assertEqual(
            header.total,
            20 * (0 + 20)
        )
        self.assertEqual(
            header.goods,
            0 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20
            # i.e. 0 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entry for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                0
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                None
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(2 * i) + 0]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(2 * i) + 1]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        vat_trans = nom_trans[::2]
        total_trans = nom_trans[1::2]

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # CORRECT USAGE
    # Zero value invoice
    # So analysis must cancel out
    # A zero value transaction is only permissable if we are matching -- a good check in the system

    def test_zero_invoice_with_analysis(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        headers_to_match_against = create_cancelling_headers(
            2, self.customer, "match", "si", 100, self.period)
        headers_to_match_against_orig = headers_to_match_against
        headers_as_dicts = [to_dict(header)
                            for header in headers_to_match_against]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 100})
        matching_forms += add_and_replace_objects([headers_to_match_against[1]], {
                                                  "id": "matched_to"}, {"value": -100})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 20,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 10
        line_forms += (
            [{
                'description': self.description,
                'goods': -20,
                'nominal': self.nominal.pk,
                'vat_code': self.vat_code.pk,
                'vat': +20
            }] * 10
        )
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 3)
        header = headers[0]
        self.assertEqual(
            header.total,
            0
        )
        self.assertEqual(
            header.goods,
            0
        )
        self.assertEqual(
            header.vat,
            0
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        lines_orig = lines
        lines = lines_orig[:10]

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            40
            # i.e. 20 nominal trans for goods
            # i.e. 20 nominal trans for vat
            # no nominal control account nominal entry because would be zero value -- WHAT THE WHOLE TEST IS ABOUT !!!
        )
        # assuming the lines are created in the same order
        # as the nominal entries....

        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                20
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(2 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(2 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                None
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        lines = lines_orig[10:]
        for i, line in enumerate(lines, 10):
            self.assertEqual(
                line.line_no,
                i + 1
            )

            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -20
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(2 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(2 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                None
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[0].value,
            100
        )

        goods_and_vat_nom_trans = nom_trans[:40]
        positive_goods_trans = goods_and_vat_nom_trans[:20:2]
        negative_vat_trans = goods_and_vat_nom_trans[1:20:2]
        negative_goods_trans = goods_and_vat_nom_trans[20::2]
        positive_vat_trans = goods_and_vat_nom_trans[21::2]

        lines = lines_orig[:10]
        for i, tran in enumerate(positive_goods_trans):
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )
        lines = lines_orig[:10]
        for i, tran in enumerate(negative_vat_trans):
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        lines = lines_orig[10:]
        for i, tran in enumerate(negative_goods_trans):
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )
        lines = lines_orig[10:]
        for i, tran in enumerate(positive_vat_trans):
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        lines = lines_orig

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # CORRECT USAGE
    # Zero value invoice again but this time with no lines
    # A zero value transaction is only permissable if we are matching -- a good check in the system
    def test_zero_invoice_with_no_analysis(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        headers_to_match_against = create_cancelling_headers(
            2, self.customer, "match", "si", 100, self.period)
        headers_to_match_against_orig = headers_to_match_against
        headers_as_dicts = [to_dict(header)
                            for header in headers_to_match_against]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 100})
        matching_forms += add_and_replace_objects([headers_to_match_against[1]], {
                                                  "id": "matched_to"}, {"value": -100})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_data = create_formset_data(LINE_FORM_PREFIX, [])
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 3)
        header = headers[0]
        self.assertEqual(
            header.total,
            0
        )
        self.assertEqual(
            header.goods,
            0
        )
        self.assertEqual(
            header.vat,
            0
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        lines = SaleLine.objects.all()
        self.assertEqual(
            len(lines),
            0
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            0
            # i.e. 20 nominal trans for goods
            # i.e. 20 nominal trans for vat
            # no nominal control account nominal entry because would be zero value -- WHAT THE WHOLE TEST IS ABOUT !!!
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[0].value,
            100
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )


    # INCORRECT USAGE
    # No point allowing lines which have no goods or vat
    def test_zero_invoice_with_line_but_goods_and_zero_are_both_zero(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        headers_to_match_against = create_cancelling_headers(
            2, self.customer, "match", "si", 100, self.period)
        headers_to_match_against_orig = headers_to_match_against
        headers_as_dicts = [to_dict(header)
                            for header in headers_to_match_against]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 100})
        matching_forms += add_and_replace_objects([headers_to_match_against[1]], {
                                                  "id": "matched_to"}, {"value": -100})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 0,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 0
        }])
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<li class="py-1">Goods and Vat cannot both be zero.</li>',
            html=True
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )

    """
    Test matching positive invoices now
    """

    # CORRECT USAGE
    def test_fully_matching_an_invoice(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(self.customer, "receipt", 1, self.period, 2400)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 2400})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (100 + 20)
        )
        self.assertEqual(
            header.goods,
            20 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            2400
        )
        self.assertEqual(
            header.due,
            0
        )

        self.assertEqual(
            receipt.total,
            -2400
        )
        self.assertEqual(
            receipt.paid,
            -2400
        )
        self.assertEqual(
            receipt.due,
            0
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                100 + 20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            1
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]  # receipt created first before invoice
        )
        self.assertEqual(
            matches[0].value,
            -2400
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # CORRECT USAGE
    def test_selecting_a_transaction_to_match_but_for_zero_value(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(self.customer, "receipt", 1, self.period, 2400)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 0})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (100 + 20)
        )
        self.assertEqual(
            header.goods,
            20 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            2400
        )

        self.assertEqual(
            receipt.total,
            -2400
        )
        self.assertEqual(
            receipt.paid,
            0
        )
        self.assertEqual(
            receipt.due,
            -2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                100 + 20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )
        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )
        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # INCORRECT USAGE
    # For an invoice of 2400 the match value must be between 0 and -2400
    def test_match_total_greater_than_zero(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        invoice_to_match = create_invoices(
            self.customer, "invoice to match", 1, self.period, 2000)[0]
        headers_as_dicts = [to_dict(invoice_to_match)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 0.01})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<li class="py-1">Please ensure the total of the transactions you are matching is between 0 and 2400.00</li>',
            html=True
        )
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 1)
        invoice_to_match = headers[0]
        self.assertEqual(
            invoice_to_match.total,
            2400
        )
        self.assertEqual(
            invoice_to_match.paid,
            0
        )
        self.assertEqual(
            invoice_to_match.due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            0
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all()
        self.assertEqual(len(lines), 0)

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )


    # INCORRECT USAGE
    # Try and match -2400.01 to an invoice for 2400
    def test_match_total_less_than_invoice_total(self):
        self.client.force_login(self.user)

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(
            self.customer, "invoice to match", 1, self.period, 2500)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 2400.01})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<li class="py-1">Please ensure the total of the transactions you are matching is between 0 and 2400.00</li>',
            html=True
        )
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 1)
        receipt = headers[0]
        self.assertEqual(
            receipt.total,
            -2500
        )
        self.assertEqual(
            receipt.paid,
            0
        )
        self.assertEqual(
            receipt.due,
            -2500
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            0
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all()
        self.assertEqual(len(lines), 0)

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )

    # CORRECT USAGE
    # We've already tested we can match the whole amount and matching 0 does not count
    # Now try matching for value in between
    def test_matching_a_value_but_not_whole_amount(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(self.customer, "receipt", 1, self.period, 2400)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 1200})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': 100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': 20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (100 + 20)
        )
        self.assertEqual(
            header.goods,
            20 * 100
        )
        self.assertEqual(
            header.vat,
            20 * 20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            1200
        )
        self.assertEqual(
            header.due,
            1200
        )

        self.assertEqual(
            receipt.total,
            -2400
        )
        self.assertEqual(
            receipt.paid,
            -1200
        )
        self.assertEqual(
            receipt.due,
            -1200
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                100 + 20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            1
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]  # receipt created first before invoice
        )
        self.assertEqual(
            matches[0].value,
            -1200
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    """
    Test negative invoices now.  I've not repeated all the tests
    that were done for positives.  We shouldn't need to.
    """

    # CORRECT USAGE
    def test_negative_invoice_entered_without_matching(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        matching_data = create_formset_data(match_form_prefix, [])
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)
        header = headers[0]
        self.assertEqual(
            header.total,
            20 * (-100 + -20)
        )
        self.assertEqual(
            header.goods,
            20 * -100
        )
        self.assertEqual(
            header.vat,
            20 * -20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                -100 + -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    def test_negative_invoice_without_matching_with_total(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": -2400
            }
        )
        data.update(header_data)
        matching_data = create_formset_data(match_form_prefix, [])
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)
        header = headers[0]
        self.assertEqual(
            header.total,
            20 * (-100 + -20)
        )
        self.assertEqual(
            header.goods,
            20 * -100
        )
        self.assertEqual(
            header.vat,
            20 * -20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            header.total
        )
        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )

            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                -100 + -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    """
    Test matching negative invoices now
    """

    # CORRECT USAGE
    def test_fully_matching_a_negative_invoice_NEGATIVE(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(
            self.customer, "receipt", 1, self.period, -2400)[0]  # NEGATIVE PAYMENT
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": -2400})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (-100 + -20)
        )
        self.assertEqual(
            header.goods,
            20 * -100
        )
        self.assertEqual(
            header.vat,
            20 * -20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            -2400
        )
        self.assertEqual(
            header.due,
            0
        )

        self.assertEqual(
            receipt.total,
            2400
        )
        self.assertEqual(
            receipt.paid,
            2400
        )
        self.assertEqual(
            receipt.due,
            0
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                -100 + -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            1
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]  # receipt created first before invoice
        )
        self.assertEqual(
            matches[0].value,
            2400
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    def test_selecting_a_transaction_to_match_but_for_zero_value_against_negative_invoice_NEGATIVE(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(
            self.customer, "receipt", 1, self.period, -2400)[0]  # NEGATIVE PAYMENT
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": 0})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (-100 + -20)
        )
        self.assertEqual(
            header.goods,
            20 * -100
        )
        self.assertEqual(
            header.vat,
            20 * -20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            0
        )
        self.assertEqual(
            header.due,
            -2400
        )

        self.assertEqual(
            receipt.total,
            2400
        )
        self.assertEqual(
            receipt.paid,
            0
        )
        self.assertEqual(
            receipt.due,
            2400
        )

        nom_trans = NominalTransaction.objects.all().order_by("module", "header", "line", "pk")
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                -100 + -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # INCORRECT USAGE
    # For an invoice of 2400 the match value must be between 0 and -2400
    def test_match_total_less_than_zero_NEGATIVE(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        invoice_to_match = create_invoices(
            self.customer, "invoice to match", 1, self.period, -2000)[0]
        headers_as_dicts = [to_dict(invoice_to_match)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": -0.01})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<li class="py-1">Please ensure the total of the transactions you are matching is between 0 and -2400.00</li>',
            html=True
        )
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 1)
        invoice_to_match = headers[0]
        self.assertEqual(
            invoice_to_match.total,
            -2400
        )
        self.assertEqual(
            invoice_to_match.paid,
            0
        )
        self.assertEqual(
            invoice_to_match.due,
            -2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            0
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all()
        self.assertEqual(len(lines), 0)

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )


    # INCORRECT USAGE
    # Try and match -2400.01 to an invoice for 2400
    def test_match_total_less_than_invoice_total_NEGATIVE(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(
            self.customer, "invoice to match", 1, self.period, -2500)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": -2400.01})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<li class="py-1">Please ensure the total of the transactions you are matching is between 0 and -2400.00</li>',
            html=True
        )
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 1)
        receipt = headers[0]
        self.assertEqual(
            receipt.total,
            2500
        )
        self.assertEqual(
            receipt.paid,
            0
        )
        self.assertEqual(
            receipt.due,
            2500
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            0
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all()
        self.assertEqual(len(lines), 0)

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )


    # CORRECT USAGE
    # We've already tested we can match the whole amount and matching 0 does not count
    # Now try matching for value in between
    def test_matching_a_value_but_not_whole_amount_NEGATIVE(self):
        self.client.force_login(self.user)
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 0
            }
        )
        data.update(header_data)
        receipt = create_receipts(self.customer, "receipt", 1, self.period, -2400)[0]
        headers_as_dicts = [to_dict(receipt)]
        headers_to_match_against = [get_fields(
            header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {
                                                  "id": "matched_to"}, {"value": -1200})
        matching_data = create_formset_data(
            match_form_prefix, matching_forms)
        line_forms = ([{
            'description': self.description,
            'goods': -100,
            'nominal': self.nominal.pk,
            'vat_code': self.vat_code.pk,
            'vat': -20
        }]) * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(matching_data)
        data.update(line_data)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 2)
        receipt = headers[0]
        header = headers[1]

        self.assertEqual(
            header.total,
            20 * (-100 + -20)
        )
        self.assertEqual(
            header.goods,
            20 * -100
        )
        self.assertEqual(
            header.vat,
            20 * -20
        )
        self.assertEqual(
            header.ref,
            self.ref
        )
        self.assertEqual(
            header.paid,
            -1200
        )
        self.assertEqual(
            header.due,
            -1200
        )

        self.assertEqual(
            receipt.total,
            2400
        )
        self.assertEqual(
            receipt.paid,
            1200
        )
        self.assertEqual(
            receipt.due,
            1200
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
            # i.e. 20 nominal entries for each goods value
            # 20 nominal entries for each vat value
            # 20 nominal entries for each goods + vat value
        )
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        for i, line in enumerate(lines):
            self.assertEqual(
                line.line_no,
                i + 1
            )
            self.assertEqual(
                line.description,
                self.description
            )
            self.assertEqual(
                line.goods,
                -100
            )
            self.assertEqual(
                line.nominal,
                self.nominal
            )
            self.assertEqual(
                line.vat_code,
                self.vat_code
            )
            self.assertEqual(
                line.vat,
                -20
            )
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[(3 * i) + 0]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[(3 * i) + 1]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[(3 * i) + 2]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_trans = nom_trans[::3]
        vat_trans = nom_trans[1::3]
        total_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.value,
                100
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'g'
            )

        for i, tran in enumerate(vat_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.value,
                20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                'v'
            )

        for i, tran in enumerate(total_trans):
            self.assertEqual(
                tran.module,
                SL_MODULE
            )
            self.assertEqual(
                tran.header,
                header.pk
            )
            self.assertEqual(
                tran.line,
                lines[i].pk
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.value,
                -100 + -20
            )
            self.assertEqual(
                tran.ref,
                header.ref
            )
            self.assertEqual(
                tran.period,
                self.period
            )
            self.assertEqual(
                tran.date,
                header.date
            )
            self.assertEqual(
                tran.field,
                't'
            )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            1
        )
        self.assertEqual(
            matches[0].matched_by,
            header
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]  # receipt created first before invoice
        )
        self.assertEqual(
            matches[0].value,
            1200
        )
        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


class EditInvoiceNominalEntries(TestCase):

    """
    Based on same tests as CreateInvoiceNominalEntries
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="dummy", password="dummy")
        cls.factory = RequestFactory()
        cls.customer = Customer.objects.create(name="test_customer")
        cls.ref = "test matching"
        cls.date = datetime.now().strftime(DATE_INPUT_FORMAT)
        cls.due_date = (datetime.now() + timedelta(days=31)).strftime(DATE_INPUT_FORMAT)
        cls.model_date = datetime.now().strftime(MODEL_DATE_INPUT_FORMAT)
        cls.model_due_date = (datetime.now() + timedelta(days=31)).strftime(MODEL_DATE_INPUT_FORMAT)
        fy = FinancialYear.objects.create(financial_year=2020)
        cls.fy = fy
        cls.period = Period.objects.create(fy=fy, period="01", fy_and_period="202001", month_start=date(2020,1,31))
        cls.description = "a line description"
        # ASSETS
        assets = Nominal.objects.create(name="Assets")
        current_assets = Nominal.objects.create(parent=assets, name="Current Assets")
        cls.nominal = Nominal.objects.create(parent=current_assets, name="Bank Account")
        cls.sale_control = Nominal.objects.create(
            parent=current_assets, name="Sales Ledger Control"
        )
        # LIABILITIES
        liabilities = Nominal.objects.create(name="Liabilities")
        current_liabilities = Nominal.objects.create(parent=liabilities, name="Current Liabilities")
        cls.vat_nominal = Nominal.objects.create(parent=current_liabilities, name="Vat")
        cls.vat_code = Vat.objects.create(code="1", name="standard rate", rate=20)
        ModuleSettings.objects.create(
            cash_book_period=cls.period,
            nominals_period=cls.period,
            purchases_period=cls.period,
            sales_period=cls.period
        )

    # CORRECT USAGE
    # Basic edit here in so far as we just change a line value
    def test_nominals_created_for_lines_with_goods_and_vat_above_zero(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )


        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, line in enumerate(lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total - 60 # we half the goods and vat for a line
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_forms[-1]["goods"] = 50
        line_forms[-1]["vat"] = 10
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2340
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2340
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        unedited_lines = list(lines)[:-1]

        for i, line in enumerate(unedited_lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )


        i = i + 1

        edited_line = lines[-1]
        self.assertEqual(edited_line.line_no, i + 1)
        self.assertEqual(edited_line.header, header)
        self.assertEqual(edited_line.description, self.description)
        self.assertEqual(edited_line.goods, 50)
        self.assertEqual(edited_line.nominal, self.nominal)
        self.assertEqual(edited_line.vat_code, self.vat_code)
        self.assertEqual(edited_line.vat, 10)
        self.assertEqual(
            edited_line.goods_nominal_transaction,
            nom_trans[ 57 ]
        )
        self.assertEqual(
            edited_line.vat_nominal_transaction,
            nom_trans[ 58 ]
        )
        self.assertEqual(
            edited_line.total_nominal_transaction,
            nom_trans[ 59 ]
        )
        self.assertEqual(
            edited_line.vat_transaction,
            vat_transactions[-1]
        )        

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        unedited_goods_nom_trans = goods_nom_trans[:-1]

        # CHECK OUR UNEDITED FIRST ARE INDEED UNEDITED

        for tran in unedited_goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        unedited_vat_nom_trans = vat_nom_trans[:-1]

        for tran in unedited_vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        unedited_total_nom_trans = total_nom_trans[:-1]

        for tran in unedited_total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        # NOW CHECK THE EDITED

        edited_goods_nom_tran = goods_nom_trans[-1]
        self.assertEqual(
            edited_goods_nom_tran.value,
            -50
        )
        self.assertEqual(
            edited_goods_nom_tran.nominal,
            self.nominal
        )
        self.assertEqual(
            edited_goods_nom_tran.field,
            "g"
        )

        edited_vat_nom_tran = vat_nom_trans[-1]
        self.assertEqual(
            edited_vat_nom_tran.value,
            -10
        )
        self.assertEqual(
            edited_vat_nom_tran.nominal,
            self.vat_nominal
        )
        self.assertEqual(
            edited_vat_nom_tran.field,
            "v"
        )

        edited_total_nom_tran = total_nom_trans[-1]
        self.assertEqual(
            edited_total_nom_tran.value,
            60
        )
        self.assertEqual(
            edited_total_nom_tran.nominal,
            self.sale_control
        )
        self.assertEqual(
            edited_total_nom_tran.field,
            "t"
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum( vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum( vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    # Add another line this time
    def test_nominals_created_for_new_line(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)

        self.assertEqual(
            len(headers),
            1
        )
        header = headers[0]
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total + 120 # we half the goods and vat for a line
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        last_line_form = line_forms[-1].copy()
        last_line_form["id"] = ""
        line_forms.append(last_line_form)
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2520
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2520
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            21 + 21 + 21
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            21
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            21
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for tran in goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        for tran in vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        for tran in total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    # Based on above
    # Except this time we reduce goods to zero on a line
    # This should delete the corresponding nominal transaction for goods
    # And obviously change the control account nominal value
    def test_goods_reduced_to_zero_but_vat_non_zero_on_a_line(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {

                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")
        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )
        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total - 100 # we set goods = 0 when previously was 100
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_forms[-1]["goods"] = 0
        line_forms[-1]["vat"] = 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2300
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2300
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            19 + 20 + 20
            # 19 goods nominal transactions
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        unedited_lines = list(lines)[:-1]

        for i, line in enumerate(unedited_lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        i = i + 1

        edited_line = lines[-1]
        self.assertEqual(edited_line.header, header)
        self.assertEqual(edited_line.line_no, i + 1)
        self.assertEqual(edited_line.description, self.description)
        self.assertEqual(edited_line.goods, 0)
        self.assertEqual(edited_line.nominal, self.nominal)
        self.assertEqual(edited_line.vat_code, self.vat_code)
        self.assertEqual(edited_line.vat, 20)
        # NOMINAL TRANSACTION FOR GOODS IS REMOVED
        self.assertEqual(
            edited_line.goods_nominal_transaction,
            None
        )
        self.assertEqual(
            edited_line.vat_nominal_transaction,
            nom_trans[ 57 ]
        )
        self.assertEqual(
            edited_line.total_nominal_transaction,
            nom_trans[ 58 ]
        )
        self.assertEqual(
            edited_line.vat_transaction,
            vat_transactions[-1]
        )

        goods_nom_trans = nom_trans[:-2:3]
        vat_nom_trans = nom_trans[1:-2:3]
        total_nom_trans = nom_trans[2:-2:3]

        unedited_goods_nom_trans = goods_nom_trans

        # CHECK OUR UNEDITED FIRST ARE INDEED UNEDITED

        for tran in unedited_goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        unedited_vat_nom_trans = vat_nom_trans

        for tran in unedited_vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        unedited_total_nom_trans = total_nom_trans

        for tran in unedited_total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        # NOW CHECK THE EDITED

        edited_vat_nom_tran = nom_trans[-2]
        self.assertEqual(
            edited_vat_nom_tran.value,
            -20
        )
        self.assertEqual(
            edited_vat_nom_tran.nominal,
            self.vat_nominal
        )
        self.assertEqual(
            edited_vat_nom_tran.field,
            "v"
        )

        edited_total_nom_tran = nom_trans[-1]
        self.assertEqual(
            edited_total_nom_tran.value,
            20
        )
        self.assertEqual(
            edited_total_nom_tran.nominal,
            self.sale_control
        )
        self.assertEqual(
            edited_total_nom_tran.field,
            "t"
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    # Same as above except we now blank out vat and not goods
    def test_vat_reduced_to_zero_but_goods_non_zero_on_a_line(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total - 20 # we set vat = 0 when previously was 20
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_forms[-1]["goods"] = 100
        line_forms[-1]["vat"] = 0
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2380
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2380
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            20 + 19 + 20
            # 19 goods nominal transactions
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        unedited_lines = list(lines)[:-1]

        for i, line in enumerate(unedited_lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        i = i + 1

        edited_line = lines[-1]
        self.assertEqual(edited_line.header, header)
        self.assertEqual(edited_line.line_no, i + 1)
        self.assertEqual(edited_line.description, self.description)
        self.assertEqual(edited_line.goods, 100)
        self.assertEqual(edited_line.nominal, self.nominal)
        self.assertEqual(edited_line.vat_code, self.vat_code)
        self.assertEqual(edited_line.vat, 0)
        # NOMINAL TRANSACTION FOR GOODS IS REMOVED
        self.assertEqual(
            edited_line.goods_nominal_transaction,
            nom_trans[ 57 ]
        )
        self.assertEqual(
            edited_line.vat_nominal_transaction,
            None
        )
        self.assertEqual(
            edited_line.total_nominal_transaction,
            nom_trans[ 58 ]
        )
        self.assertEqual(
            edited_line.vat_transaction,
            vat_transactions[-1]
        )        

        goods_nom_trans = nom_trans[:-2:3]
        vat_nom_trans = nom_trans[1:-2:3]
        total_nom_trans = nom_trans[2:-2:3]

        unedited_goods_nom_trans = goods_nom_trans

        # CHECK OUR UNEDITED FIRST ARE INDEED UNEDITED

        for tran in unedited_goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        unedited_vat_nom_trans = vat_nom_trans

        for tran in unedited_vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        unedited_total_nom_trans = total_nom_trans

        for tran in unedited_total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        # NOW CHECK THE EDITED

        edited_goods_nom_tran = nom_trans[-2]
        self.assertEqual(
            edited_goods_nom_tran.value,
            -100
        )
        self.assertEqual(
            edited_goods_nom_tran.nominal,
            self.nominal
        )
        self.assertEqual(
            edited_goods_nom_tran.field,
            "g"
        )

        edited_total_nom_tran = nom_trans[-1]
        self.assertEqual(
            edited_total_nom_tran.value,
            100
        )
        self.assertEqual(
            edited_total_nom_tran.nominal,
            self.sale_control
        )
        self.assertEqual(
            edited_total_nom_tran.field,
            "t"
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    # CORRECT USAGE
    # Zero out the goods and the vat
    # We expect the line and the three nominal transactions to all be deleted
    def test_goods_and_vat_for_line_reduced_to_zero(self):
        self.client.force_login(self.user)
 
        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {

                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total - 120 # we set vat = 0 when previously was 20
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_forms[-1]["goods"] = 0
        line_forms[-1]["vat"] = 0
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})
        response = self.client.post(url, data)
        self.assertEqual(
            response.status_code,
            200
        )
        self.assertContains(
            response,
            '<li class="py-1">Goods and Vat cannot both be zero.</li>',
            html=True
        )

    # CORRECT USAGE
    # SIMPLY MARK A LINE AS DELETED
    def test_line_marked_as_deleted_has_line_and_nominals_removed(self):
        self.client.force_login(self.user)
 
        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {

                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total - 120 # we set vat = 0 when previously was 20
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_forms[-1]["goods"] = 100
        line_forms[-1]["vat"] = 20
        line_forms[-1]["DELETE"] = "yes"
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2280
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2280
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            19 + 19 + 19
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            19
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            19
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        unedited_lines = list(lines)[:-1]

        for i, line in enumerate(unedited_lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no , i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )



        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        unedited_goods_nom_trans = goods_nom_trans

        # CHECK OUR UNEDITED FIRST ARE INDEED UNEDITED

        for tran in unedited_goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        unedited_vat_nom_trans = vat_nom_trans

        for tran in unedited_vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        unedited_total_nom_trans = total_nom_trans

        for tran in unedited_total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )        


    # CORRECT USAGE
    # DELETE ALL THE LINES SO IT IS A ZERO INVOICE
    def test_non_zero_invoice_is_changed_to_zero_invoice_by_deleting_all_lines(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": 0
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        for form in line_forms:
            form["DELETE"] = "yes"
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        # WE HAVE TO MATCH OTHERWISE IT WILL ERROR
        headers_to_match_against = create_cancelling_headers(2, self.customer, "match", "si", 100, self.period)
        headers_to_match_against_orig = headers_to_match_against
        headers_as_dicts = [ to_dict(header) for header in headers_to_match_against ]
        headers_to_match_against = [ get_fields(header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts ]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {"id": "matched_to"}, {"value": 100})
        matching_forms += add_and_replace_objects([headers_to_match_against[1]], {"id": "matched_to"}, {"value": -100})
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(len(headers), 3)

        self.assertEqual(
            headers[0].total,
            0
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            0
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            0
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            0
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)
    
        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[0].value,
            100
        )   
        self.assertEqual(
            matches[1].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[1].matched_to,
            headers[2]
        )
        self.assertEqual(
            matches[1].value,
            -100
        )  


    # CORRECT USAGE
    def test_change_zero_invoice_to_a_non_zero_invoice(self):
        self.client.force_login(self.user)

        header = SaleHeader.objects.create(
            **{
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "goods": 0,
                "vat": 0,
                "total": 0,
                "paid": 0,
                "due": 0
            }
        )

        headers_to_match_against = create_cancelling_headers(2, self.customer, "match", "si", 100, self.period)
        match(header, [ (headers_to_match_against[0], 100), (headers_to_match_against[1], -100) ] )

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            3
        )
        self.assertEqual(
            headers[0].total,
            0
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            0
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[0].value,
            100
        )   
        self.assertEqual(
            matches[1].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[1].matched_to,
            headers[2]
        )
        self.assertEqual(
            matches[1].value,
            -100
        ) 

        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            0
        )

        header = headers[0]

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": 2400
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ] * 20
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)

        # WE HAVE TO MATCH OTHERWISE IT WILL ERROR
        headers_to_match_against_orig = headers_to_match_against
        headers_as_dicts = [ to_dict(header) for header in headers_to_match_against ]
        headers_to_match_against = [ get_fields(header, ['type', 'ref', 'total', 'paid', 'due', 'id']) for header in headers_as_dicts ]
        matching_forms = []
        matching_forms += add_and_replace_objects([headers_to_match_against[0]], {"id": "matched_to"}, {"value": 100})
        matching_forms += add_and_replace_objects([headers_to_match_against[1]], {"id": "matched_to"}, {"value": -100})
        matching_forms[0]["id"] = matches[0].pk
        matching_forms[1]["id"] = matches[1].pk
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        matching_data["match-INITIAL_FORMS"] = 2
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": header.pk})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            3
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )
        self.assertEqual(
            headers[1].total,
            100
        )
        self.assertEqual(
            headers[1].paid,
            100
        )
        self.assertEqual(
            headers[1].due,
            0
        )
        self.assertEqual(
            headers[2].total,
            -100
        )
        self.assertEqual(
            headers[2].paid,
            -100
        )
        self.assertEqual(
            headers[2].due,
            0
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        nom_trans = NominalTransaction.objects.all().order_by("pk")
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[0].value,
            100
        )   
        self.assertEqual(
            matches[1].matched_by,
            headers[0]
        )
        self.assertEqual(
            matches[1].matched_to,
            headers[2]
        )
        self.assertEqual(
            matches[1].value,
            -100
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )


    # INCORRECT USAGE
    def test_new_matched_value_is_ok_for_transaction_being_edited_but_not_for_matched_transaction_1(self):
        self.client.force_login(self.user)

        # Create an invoice for 120.01 through view first
        # Second create a credit note for 120.00
        # Third create an invoice for -0.01 and match the other two to it
        # Invalid edit follows

        # Invoice for 120.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)
        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        # Credit Note for 120.00
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "sc",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.00
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.00,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)
        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            2
        )

        # Invoice for -0.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": -0.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': -0.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 0
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)

        matching_forms = []
        matching_forms.append({
            "type": headers[0].type,
            "ref": headers[0].ref,
            "total": headers[0].total,
            "paid": headers[0].paid,
            "due": headers[0].due,
            "matched_by": '',
            "matched_to": headers[0].pk,
            "value": headers[0].total,
        })
        matching_forms.append({
            "type": headers[1].type,
            "ref": headers[1].ref,
            "total": headers[1].total * -1,
            "paid": headers[1].paid * -1,
            "due": headers[1].due * -1,
            "matched_by": '',
            "matched_to": headers[1].pk,
            "value": headers[1].total * -1,
        })
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        data.update(matching_data)
        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            3
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            headers[2]
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]
        )
        self.assertEqual(
            matches[0].value,
            two_dp(120.01)
        )
        self.assertEqual(
            matches[1].matched_by,
            headers[2]
        )
        self.assertEqual(
            matches[1].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[1].value,
            -120
        )

        # Now for the edit.  In the UI the match value shows as -120.01.  In the DB it shows as 120.01
        # We want to change the value to 110.01.  This isn't ok because the -0.01 invoice can only be
        # matched for 0 and full value.  The edit will mean the matched will be outside this.

        lines = SaleLine.objects.filter(header=headers[0]).all()
        self.assertEqual(
            len(lines),
            1
        )

        # Invoice for 120.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_forms[0]["id"] = lines[0].pk
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 1 
        data.update(line_data)

        matching_forms = []
        matching_forms.append({
            "type": headers[2].type,
            "ref": headers[2].ref,
            "total": headers[2].total,
            "paid": headers[2].paid,
            "due": headers[2].due,
            "matched_by": headers[2].pk,
            "matched_to": headers[0].pk,
            "value": '-110.01',
            "id": matches[0].pk
        })
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        matching_data["match-INITIAL_FORMS"] = 1
        data.update(matching_data)

        response = self.client.post(reverse("sales:edit", kwargs={"pk": headers[0].pk}), data)
        self.assertEqual(
            response.status_code,
            200
        )


    # INCORRECT USAGE
    def test_new_matched_value_is_ok_for_transaction_being_edited_but_not_for_matched_transaction_2(self):
        self.client.force_login(self.user)

        # Create an invoice for 120.01 through view first
        # Second create a credit note for 120.00
        # Third create an invoice for -0.01 and match the other two to it
        # Invalid edit follows

        # Invoice for 120.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)
        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        # Credit Note for 120.00
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "sc",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.00
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.00,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)
        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            2
        )

        # Invoice for -0.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": -0.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': -0.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 0
                }
        ]
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        data.update(line_data)

        matching_forms = []
        matching_forms.append({
            "type": headers[0].type,
            "ref": headers[0].ref,
            "total": headers[0].total,
            "paid": headers[0].paid,
            "due": headers[0].due,
            "matched_by": '',
            "matched_to": headers[0].pk,
            "value": headers[0].total,
        })
        matching_forms.append({
            "type": headers[1].type,
            "ref": headers[1].ref,
            "total": headers[1].total * -1,
            "paid": headers[1].paid * -1,
            "due": headers[1].due * -1,
            "matched_by": '',
            "matched_to": headers[1].pk,
            "value": headers[1].total * -1,
        })
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        data.update(matching_data)
        response = self.client.post(reverse("sales:create"), data)
        self.assertEqual(
            response.status_code,
            302
        )

        headers = SaleHeader.objects.all().order_by("pk")
        self.assertEqual(
            len(headers),
            3
        )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            2
        )
        self.assertEqual(
            matches[0].matched_by,
            headers[2]
        )
        self.assertEqual(
            matches[0].matched_to,
            headers[0]
        )
        self.assertEqual(
            matches[0].value,
            two_dp(120.01)
        )
        self.assertEqual(
            matches[1].matched_by,
            headers[2]
        )
        self.assertEqual(
            matches[1].matched_to,
            headers[1]
        )
        self.assertEqual(
            matches[1].value,
            -120
        )

        # Now for the edit.  In the UI the match value shows as -120.01.  In the DB it shows as 120.01
        # We want to change the value to 110.01.  This isn't ok because the -0.01 invoice can only be
        # matched for 0 and full value.  The edit will mean the matched will be outside this.

        lines = SaleLine.objects.filter(header=headers[0]).all()
        self.assertEqual(
            len(lines),
            1
        )

        # Invoice for 120.01
        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": "si",
                "customer": self.customer.pk,
				"period": self.period.pk,
                "ref": self.ref,
                "date": self.date,
                "due_date": self.due_date,
                "total": 120.01
            }
        )
        data.update(header_data)
        line_forms = [
                {
                    
                    'description': self.description,
                    'goods': 100.01,
                    'nominal': self.nominal.pk,
                    'vat_code': self.vat_code.pk,
                    'vat': 20
                }
        ]
        line_forms[0]["id"] = lines[0].pk
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 1 
        data.update(line_data)

        matching_forms = []
        matching_forms.append({
            "type": headers[2].type,
            "ref": headers[2].ref,
            "total": headers[2].total,
            "paid": headers[2].paid,
            "due": headers[2].due,
            "matched_by": headers[2].pk,
            "matched_to": headers[0].pk,
            "value": '-120.02',
            "id": matches[0].pk
        })
        matching_data = create_formset_data(match_form_prefix, matching_forms)
        matching_data["match-INITIAL_FORMS"] = 1
        data.update(matching_data)

        response = self.client.post(reverse("sales:edit", kwargs={"pk": headers[0].pk}), data)
        self.assertEqual(
            response.status_code,
            200
        )


    # INCORRECT USAGE
    # Add another line this time
    def test_new_line_marked_as_deleted_does_not_count(self):
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )

        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )


        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        last_line_form = line_forms[-1].copy()
        last_line_form["id"] = ""
        last_line_form["DELETE"] = "YEP"
        line_forms.append(last_line_form)
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        for i, line in enumerate(lines):
            self.assertEqual(line.header, header)
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for tran in goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )

        for tran in vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )

        for tran in total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )

        # NOW CHECK THE EDITED

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                header.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )


        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

    def test_edit_header_only(self):
        # change period in header only and check period for NL, VL trans is updated
        self.client.force_login(self.user)

        create_invoice_with_nom_entries(
            {
                "type": "si",
                "customer": self.customer,
				"period": self.period,
                "ref": self.ref,
                "date": self.model_date,
                "due_date": self.model_due_date,
                "total": 2400,
                "paid": 0,
                "due": 2400,
                "goods": 2000,
                "vat": 400,
                "period": self.period
            },
            [
                {
                    'description': self.description,
                    'goods': 100,
                    'nominal': self.nominal,
                    'vat_code': self.vat_code,
                    'vat': 20
                }
            ] * 20,
            self.vat_nominal,
            self.sale_control
        )

        headers = SaleHeader.objects.all().order_by("pk")

        lines = SaleLine.objects.all().order_by("pk")
        self.assertEqual(
            len(lines),
            20
        )

        create_vat_transactions(headers[0], lines)
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )


        self.assertEqual(
            len(headers),
            1
        )
        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )
        self.assertEqual(
            headers[0].period,
            self.period
        )

        nom_trans = NominalTransaction.objects.all()
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])

        header = headers[0]

        for i, line in enumerate(lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                self.period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum(vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum(vat_tran.vat for vat_tran in vat_transactions)
        )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]

        for i, tran in enumerate(goods_nom_trans):
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                lines[i].goods_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.period,
                self.period
            )

        for i, tran in enumerate(vat_nom_trans):
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                lines[i].vat_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.period,
                self.period
            )

        for i, tran in enumerate(total_nom_trans):
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                lines[i].total_nominal_transaction,
                tran
            )
            self.assertEqual(
                tran.period,
                self.period
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        new_period = Period.objects.create(fy=self.fy, period="08", fy_and_period="202008", month_start=date(2020,2,29))

        data = {}
        header_data = create_header(
            HEADER_FORM_PREFIX,
            {
                "type": header.type,
                "customer": header.customer.pk,
				"period": header.period.pk,
                "ref": header.ref,
                "date": header.date.strftime(DATE_INPUT_FORMAT),
                "due_date": header.due_date.strftime(DATE_INPUT_FORMAT),
                "total": header.total,
                "period": new_period.pk
            }
        )
        data.update(header_data)

        lines_as_dicts = [ to_dict(line) for line in lines ]
        line_trans = [ get_fields(line, ['id',  'description', 'goods', 'nominal', 'vat_code', 'vat']) for line in lines_as_dicts ]
        line_forms = line_trans
        line_data = create_formset_data(LINE_FORM_PREFIX, line_forms)
        line_data["line-INITIAL_FORMS"] = 20
        data.update(line_data)

        matching_data = create_formset_data(match_form_prefix, [])
        data.update(matching_data)

        url = reverse("sales:edit", kwargs={"pk": headers[0].pk})

        response = self.client.post(url, data)

        headers = SaleHeader.objects.all()
        self.assertEqual(len(headers), 1)

        self.assertEqual(
            headers[0].total,
            2400
        )
        self.assertEqual(
            headers[0].paid,
            0
        )
        self.assertEqual(
            headers[0].due,
            2400
        )
        self.assertEqual(
            headers[0].period,
            new_period
        )

        nom_trans = NominalTransaction.objects.all()
        nom_trans = sort_multiple(nom_trans, *[ (lambda n : n.pk, False) ])
        self.assertEqual(
            len(nom_trans),
            20 + 20 + 20
        )

        header = headers[0]
        lines = (
            SaleLine.objects
            .select_related("vat_code")
            .all()
            .order_by("pk")
        )
        self.assertEqual(
            len(lines),
            20
        )
        vat_transactions = VatTransaction.objects.all().order_by("line")
        self.assertEqual(
            len(vat_transactions),
            20
        )
        vat_transactions = list(vat_transactions)
        lines = list(lines)

        for i, line in enumerate(lines):
            self.assertEqual(line.line_no, i + 1)
            self.assertEqual(line.header, header)
            self.assertEqual(line.description, self.description)
            self.assertEqual(line.goods, 100)
            self.assertEqual(line.nominal, self.nominal)
            self.assertEqual(line.vat_code, self.vat_code)
            self.assertEqual(line.vat, 20)
            self.assertEqual(
                line.goods_nominal_transaction,
                nom_trans[ 3 * i ]
            )
            self.assertEqual(
                line.vat_nominal_transaction,
                nom_trans[ (3 * i) + 1 ]
            )
            self.assertEqual(
                line.total_nominal_transaction,
                nom_trans[ (3 * i) + 2 ]
            )
            self.assertEqual(
                line.vat_transaction,
                vat_transactions[i]
            )

        goods_nom_trans = nom_trans[::3]
        vat_nom_trans = nom_trans[1::3]
        total_nom_trans = nom_trans[2::3]


        for tran in goods_nom_trans:
            self.assertEqual(
                tran.value,
                -100
            )
            self.assertEqual(
                tran.nominal,
                self.nominal
            )
            self.assertEqual(
                tran.field,
                "g"
            )
            self.assertEqual(
                tran.period,
                new_period
            )

        for tran in vat_nom_trans:
            self.assertEqual(
                tran.value,
                -20
            )
            self.assertEqual(
                tran.nominal,
                self.vat_nominal
            )
            self.assertEqual(
                tran.field,
                "v"
            )
            self.assertEqual(
                tran.period,
                new_period
            )

        for tran in total_nom_trans:
            self.assertEqual(
                tran.value,
                120
            )
            self.assertEqual(
                tran.nominal,
                self.sale_control
            )
            self.assertEqual(
                tran.field,
                "t"
            )
            self.assertEqual(
                tran.period,
                new_period
            )

        matches = SaleMatching.objects.all()
        self.assertEqual(
            len(matches),
            0
        )

        total = 0
        for tran in nom_trans:
            total = total + tran.value
        self.assertEqual(
            total,
            0
        )

        for i, vat_tran in enumerate(vat_transactions):
            self.assertEqual(
                vat_tran.header,
                header.pk
            )
            self.assertEqual(
                vat_tran.line,
                lines[i].pk
            )
            self.assertEqual(
                vat_tran.module,
                "SL"
            )
            self.assertEqual(
                vat_tran.ref,
                header.ref
            )
            self.assertEqual(
                vat_tran.period,
                new_period
            )
            self.assertEqual(
                vat_tran.date,
                header.date
            )
            self.assertEqual(
                vat_tran.field,
                "v"
            )
            self.assertEqual(
                vat_tran.tran_type,
                header.type
            )
            self.assertEqual(
                vat_tran.vat_type,
                "o"
            )
            self.assertEqual(
                vat_tran.vat_code,
                lines[i].vat_code
            )
            self.assertEqual(
                vat_tran.vat_rate,
                lines[i].vat_code.rate
            )
            self.assertEqual(
                vat_tran.goods,
                lines[i].goods
            )
            self.assertEqual(
                vat_tran.vat,
                lines[i].vat
            )

        self.assertEqual(
            header.goods,
            sum( vat_tran.goods for vat_tran in vat_transactions)
        )

        self.assertEqual(
            header.vat,
            sum( vat_tran.vat for vat_tran in vat_transactions)
        )

from datetime import timedelta

from django.utils import timezone

from accountancy.helpers import sort_multiple
from cashbook.models import CashBookTransaction
from nominals.models import NominalTransaction
from vat.models import VatTransaction

from .models import PurchaseHeader, PurchaseLine, Supplier

PERIOD = '202007'

def create_lines(header, lines):
    tmp = []
    for i, line in enumerate(lines):
        line["line_no"] = i + 1
        line["header"] = header
        tmp.append(PurchaseLine(**line))
    return PurchaseLine.objects.bulk_create(tmp)


def create_invoices(supplier, ref_prefix, n, period, value=100):
    date = timezone.now()
    due_date = date + timedelta(days=31)
    invoices = []
    for i in range(n):
        i = PurchaseHeader(
            supplier=supplier,
            ref=ref_prefix + str(i),
            goods=value,
            vat=0.2 * value,
            total=1.2 * value,
            paid=0,
            due=1.2 * value,
            date=date,
            due_date=due_date,
            type="pi",
            period=period
        )
        invoices.append(i)
    return PurchaseHeader.objects.bulk_create(invoices)


def create_invoice_with_lines(header, lines):
    header = PurchaseHeader.objects.create(**header)
    lines = create_lines(header, lines)
    return header, lines


def create_credit_note_with_lines(header, lines):
    header["paid"] *= -1
    header["total"] *= -1
    header["due"] *= -1
    header = PurchaseHeader.objects.create(**header)
    # this assumes lines[n] is line[0] for all n
    lines[0]["goods"] *= -1
    lines[0]["vat"] *= -1
    lines = create_lines(header, lines)
    return header, lines


def create_payments(supplier, ref_prefix, n, period, value=100):
    date = timezone.now()
    due_date = date + timedelta(days=31)
    payments = []
    for i in range(n):
        p = PurchaseHeader(
            supplier=supplier,
            ref=ref_prefix + str(i),
            total=-1 * value,
            paid=0,
            due=-1 * value,
            date=date,
            type="pp",
            period=period
        )
        payments.append(p)
    return PurchaseHeader.objects.bulk_create(payments)


def create_invoice_with_nom_entries(header, lines, vat_nominal, control_nominal):
    header = PurchaseHeader.objects.create(**header)
    lines = create_lines(header, lines)
    nom_trans = []
    for line in lines:
        if line.goods:
            nom_trans.append(
                NominalTransaction(
                    module="PL",
                    header=header.pk,
                    line=line.pk,
                    nominal=line.nominal,
                    value=line.goods,
                    ref=header.ref,
                    period=header.period,
                    date=header.date,
                    field="g",
                    type=header.type
                )
            )
        if line.vat:
            nom_trans.append(
                NominalTransaction(
                    module="PL",
                    header=header.pk,
                    line=line.pk,
                    nominal=vat_nominal,
                    value=line.vat,
                    ref=header.ref,
                    period=header.period,
                    date=header.date,
                    field="v",
                    type=header.type
                )
            )
        if line.goods or line.vat:
            nom_trans.append(
                NominalTransaction(
                    module="PL",
                    header=header.pk,
                    line=line.pk,
                    nominal=control_nominal,
                    value=-1 * (line.goods + line.vat),
                    ref=header.ref,
                    period=header.period,
                    date=header.date,
                    field="t",
                    type=header.type
                )
            )
    nom_trans = NominalTransaction.objects.bulk_create(nom_trans)
    nom_trans = sort_multiple(nom_trans, *[(lambda n: n.line, False)])
    goods_and_vat = nom_trans[:-1]
    for i, line in enumerate(lines):
        line.goods_nominal_transaction = nom_trans[3 * i]
        line.vat_nominal_transaction = nom_trans[(3 * i) + 1]
        line.total_nominal_transaction = nom_trans[(3 * i) + 2]
    PurchaseLine.objects.bulk_update(
        lines,
        ["goods_nominal_transaction", "vat_nominal_transaction",
            "total_nominal_transaction"]
    )
    return header


def create_payment_with_nom_entries(header, control_nominal, bank_nominal):
    header["total"] *= -1
    header["due"] *= -1
    header["paid"] *= -1
    header["goods"] = 0
    header["vat"] = 0
    header = PurchaseHeader.objects.create(**header)
    if header.total != 0:
        nom_trans = []
        nom_trans.append(
            NominalTransaction(
                module="PL",
                header=header.pk,
                line=1,
                nominal=bank_nominal,
                value=header.total,
                ref=header.ref,
                period=header.period,
                date=header.date,
                field="t",
                type=header.type
            )
        )
        nom_trans.append(
            NominalTransaction(
                module="PL",
                header=header.pk,
                line=2,
                nominal=control_nominal,
                value=-1 * header.total,
                ref=header.ref,
                period=header.period,
                date=header.date,
                field="t",
                type=header.type
            )
        )
        nom_trans = NominalTransaction.objects.bulk_create(nom_trans)
        CashBookTransaction.objects.create(
            module="PL",
            header=header.pk,
            line=1,
            cash_book=header.cash_book,
            value=header.total,
            ref=header.ref,
            period=header.period,
            date=header.date,
            field="t",
            type=header.type
        )
        return header


def create_refund_with_nom_entries(header, control_nominal, bank_nominal):
    # positive inputted, turn negative, then turned positive again in create_payment_with_nom
    header["total"] *= -1
    header["due"] *= -1
    header["paid"] *= -1
    # done this way because i created other function first
    return create_payment_with_nom_entries(header, control_nominal, bank_nominal)


def create_credit_note_with_nom_entries(header, lines, vat_nominal, control_nominal):
    header["total"] = -1 * header["total"]
    header["due"] = -1 * header["due"]
    header["paid"] = -1 * header["paid"]
    header["goods"] = -1 * header["goods"]
    header["vat"] = -1 * header["vat"]
    # lines is assumed to be of form [ {} ] * N
    # thus each object is in fact the same object in memory
    lines[0]["goods"] = -1 * lines[0]["goods"]
    lines[0]["vat"] = -1 * lines[0]["vat"]
    return create_invoice_with_nom_entries(header, lines, vat_nominal, control_nominal)


def create_vat_transactions(header, lines):
    vat_trans = []
    for line in lines:
        vat_trans.append(
            VatTransaction(
                header=header.pk,
                line=line.pk,
                module="PL",
                ref=header.ref,
                period=header.period,
                date=header.date,
                field="v",
                tran_type=header.type,
                vat_type="i",
                vat_code=line.vat_code,
                vat_rate=line.vat_code.rate,
                goods=line.goods,
                vat=line.vat
            )
        )
    vat_trans = VatTransaction.objects.bulk_create(vat_trans)
    vat_trans = sort_multiple(vat_trans, *[ (lambda v : v.line, False) ])
    lines = sort_multiple(lines, *[ (lambda l : l.pk, False) ])
    for i, line in enumerate(lines):
        line.vat_transaction = vat_trans[i]
    PurchaseLine.objects.bulk_update(lines, ["vat_transaction"])
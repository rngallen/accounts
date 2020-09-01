# Generated by Django 3.0.8 on 2020-08-31 15:29

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cashbook', '0003_cashbookline_total_nominal_transaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='CashBookTransaction',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('module', models.CharField(max_length=3)),
                ('header', models.PositiveIntegerField()),
                ('line', models.PositiveIntegerField()),
                ('value', models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ('ref', models.CharField(max_length=100)),
                ('period', models.CharField(max_length=6)),
                ('date', models.DateField()),
                ('created', models.DateTimeField(auto_now=True)),
                ('field', models.CharField(choices=[('g', 'Goods'), ('v', 'Vat'), ('t', 'Total')], max_length=2)),
                ('type', models.CharField(choices=[('pp', 'Payment'), ('pr', 'Refund'), ('pi', 'Invoice'), ('pc', 'Credit Note'), ('sp', 'Receipt'), ('sr', 'Refund'), ('si', 'Invoice'), ('sc', 'Credit Note'), ('cp', 'Payment'), ('cr', 'Receipt')], max_length=10)),
                ('cash_book', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='cashbook.CashBook')),
            ],
        ),
        migrations.AddConstraint(
            model_name='cashbooktransaction',
            constraint=models.UniqueConstraint(fields=('module', 'header', 'line', 'field'), name='cashbook_unique_batch'),
        ),
    ]
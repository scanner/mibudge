# Seed the 150 global TransactionCategory rows.
#
# The pairs are the old TransactionCategory TextChoices enum values
# (deleted in this change set, hence inlined here as a literal),
# split on the first colon with whitespace stripped, minus the
# "Uncategorized:Unassigned" sentinel -- NULL now means unassigned.
#
# importers/harvest_bofa_categories.py carries a copy of this list for
# its standalone dry-run resolution; keep the two in sync.

from django.db import migrations

GLOBAL_CATEGORIES: list[tuple[str, str]] = [
    ("Business", "Business Clothing"),
    ("Business", "Business Services"),
    ("Business", "Business Supplies"),
    ("Business", "Meals"),
    ("Business", "Travel"),
    ("Children", "Activities"),
    ("Children", "Allowance"),
    ("Children", "Baby Supplies"),
    ("Children", "Childcare"),
    ("Children", "Kids Clothing"),
    ("Children", "Kids Education"),
    ("Children", "Toys"),
    ("Culture", "Art"),
    ("Culture", "Books"),
    ("Culture", "Dance"),
    ("Culture", "Games"),
    ("Culture", "Movies"),
    ("Culture", "Music"),
    ("Culture", "News"),
    ("Culture", "Random Fun"),
    ("Culture", "TV"),
    ("Education", "Books & Supplies"),
    ("Education", "Room & Board"),
    ("Education", "Student Loans"),
    ("Education", "Tuition & Fees"),
    ("Fees", "ATM Fees"),
    ("Fees", "Investment Fees"),
    ("Fees", "Other Fees"),
    ("Financial", "Accounting"),
    ("Financial", "Credit Card Payment"),
    ("Financial", "Financial Advice"),
    ("Financial", "Life Insurance"),
    ("Financial", "Loan"),
    ("Financial", "Loan Payment"),
    ("Financial", "Money Transfers"),
    ("Financial", "Other Financial"),
    ("Financial", "Tax Preparation"),
    ("Financial", "Taxes, Federal"),
    ("Financial", "Taxes, Other"),
    ("Financial", "Taxes, State"),
    ("Food & Drink", "Alcohol & Bars"),
    ("Food & Drink", "Coffee & Tea"),
    ("Food & Drink", "Dessert"),
    ("Food & Drink", "Fast Food"),
    ("Food & Drink", "Groceries"),
    ("Food & Drink", "Other Food & Drink"),
    ("Food & Drink", "Restaurants"),
    ("Food & Drink", "Snacks"),
    ("Food & Drink", "Tobacco & Like"),
    ("Gifts & Donations", "Charities"),
    ("Gifts & Donations", "Gifts"),
    ("Health & Medical", "Care Facilities"),
    ("Health & Medical", "Dentist"),
    ("Health & Medical", "Doctor"),
    ("Health & Medical", "Equipment"),
    ("Health & Medical", "Eyes"),
    ("Health & Medical", "Health Insurance"),
    ("Health & Medical", "Other Health & Medical"),
    ("Health & Medical", "Pharmacies"),
    ("Health & Medical", "Prescriptions"),
    ("Home", "Furnishings"),
    ("Home", "Home Insurance"),
    ("Home", "Home Purchase"),
    ("Home", "Home Services"),
    ("Home", "Home Supplies"),
    ("Home", "Lawn & Garden"),
    ("Home", "Mortgage"),
    ("Home", "Moving"),
    ("Home", "Other Home"),
    ("Home", "Property Tax"),
    ("Home", "Rent"),
    ("Home", "Renter's Insurance"),
    ("Income", "Bonus"),
    ("Income", "Commission"),
    ("Income", "Interest"),
    ("Income", "Other Income"),
    ("Income", "Paycheck"),
    ("Income", "Reimbursement"),
    ("Income", "Rental Income"),
    ("Investment", "Education Investment"),
    ("Investment", "Other Investments"),
    ("Investment", "Retirement"),
    ("Investment", "Stocks & Mutual Funds"),
    ("Legal", "Legal Fees"),
    ("Legal", "Legal Services"),
    ("Legal", "Other Legal Costs"),
    ("Office", "Equipment"),
    ("Office", "Office Supplies"),
    ("Office", "Other Office"),
    ("Office", "Postage & Shipping"),
    ("Personal", "Accessories"),
    ("Personal", "Beauty"),
    ("Personal", "Body Enhancement"),
    ("Personal", "Clothing"),
    ("Personal", "Counseling"),
    ("Personal", "Hair"),
    ("Personal", "Hobbies"),
    ("Personal", "Jewelry"),
    ("Personal", "Laundry"),
    ("Personal", "Other Personal"),
    ("Personal", "Religion"),
    ("Personal", "Shoes"),
    ("Pets", "Pet Food"),
    ("Pets", "Pet Grooming"),
    ("Pets", "Pet Medicine"),
    ("Pets", "Pet Supplies"),
    ("Pets", "Veterinarian"),
    ("Sports & Fitness", "Camping"),
    ("Sports & Fitness", "Fitness Gear"),
    ("Sports & Fitness", "Golf"),
    ("Sports & Fitness", "Memberships"),
    ("Sports & Fitness", "Other Sports & Fitness"),
    ("Sports & Fitness", "Sporting Events"),
    ("Sports & Fitness", "Sporting Goods"),
    ("Technology", "Domains & Hosting"),
    ("Technology", "Hardware"),
    ("Technology", "Online Services"),
    ("Technology", "Software"),
    ("Transportation", "Auto Insurance"),
    ("Transportation", "Auto Payment"),
    ("Transportation", "Auto Services"),
    ("Transportation", "Auto Supplies"),
    ("Transportation", "Bicycle"),
    ("Transportation", "Boats & Marine"),
    ("Transportation", "Gas"),
    ("Transportation", "Other Transportation"),
    ("Transportation", "Parking & Tolls"),
    ("Transportation", "Parking Tickets"),
    ("Transportation", "Public Transit"),
    ("Transportation", "Shipping"),
    ("Transportation", "Taxies"),
    ("Travel", "Car Rental"),
    ("Travel", "Flights"),
    ("Travel", "Hotels"),
    ("Travel", "Tours & Cruises"),
    ("Travel", "Train"),
    ("Travel", "Travel Buses"),
    ("Travel", "Travel Dining"),
    ("Travel", "Travel Entertainment"),
    ("Uncategorized", "Cash"),
    ("Uncategorized", "Other Shopping"),
    ("Uncategorized", "Unknown"),
    ("Utilities", "Cable"),
    ("Utilities", "Electricity"),
    ("Utilities", "Gas & Fuel"),
    ("Utilities", "Internet"),
    ("Utilities", "Other Utilities"),
    ("Utilities", "Phone"),
    ("Utilities", "Trash"),
    ("Utilities", "Water & Sewer"),
]


def seed_categories(apps, schema_editor):
    """Create one global (owner NULL) row per seed pair."""
    TransactionCategory = apps.get_model("moneypools", "TransactionCategory")
    existing = {
        (g.casefold(), n.casefold())
        for g, n in TransactionCategory.objects.filter(
            owner__isnull=True
        ).values_list("group", "name")
    }
    TransactionCategory.objects.bulk_create(
        TransactionCategory(group=group, name=name, owner=None)
        for group, name in GLOBAL_CATEGORIES
        if (group.casefold(), name.casefold()) not in existing
    )


def unseed_categories(apps, schema_editor):
    """Delete the seeded global rows (custom user rows are untouched)."""
    TransactionCategory = apps.get_model("moneypools", "TransactionCategory")
    seeded = {(g.casefold(), n.casefold()) for g, n in GLOBAL_CATEGORIES}
    for category in TransactionCategory.objects.filter(owner__isnull=True):
        if (category.group.casefold(), category.name.casefold()) in seeded:
            category.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("moneypools", "0037_transaction_category_models"),
    ]

    operations = [
        migrations.RunPython(seed_categories, unseed_categories),
    ]

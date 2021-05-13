from django.conf import settings
from django.contrib.auth.models import User
from django.db import models

from djchoices import ChoiceItem, DjangoChoices
from djmoney.models.fields import MoneyField
import recurrence.fields

# See https://stackoverflow.com/questions/224462/storing-money-in-a-decimal-column-what-precision-and-scale/224866#224866
#
MAX_DIGITS = 14
DECIMAL_PLACES = 2


########################################################################
########################################################################
#
class MoneyPoolBaseClass(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


########################################################################
########################################################################
#
class Bank(MoneyPoolBaseClass):
    """
    We are dealing with your money stored in bank accounts in the
    banks you have accounts with.
    """

    name = models.CharField(max_length=200)
    # XXX Add a validator to make sure only digits are used
    routing_number = models.CharField(max_length=9, null=True, default=None)


########################################################################
########################################################################
#
class BankAccount(MoneyPoolBaseClass):
    """
    This app is about budgeting your money but as a view in to your
    bank account's money. Thus the fundamental aspect of a Budget is
    which bank account it is tied to.
    """

    name = models.CharField(max_length=200)
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE)
    owners = models.ManyToManyField(User)

    # XXX Add a validator to make sure only digits are used
    account_number = models.CharField(max_length=12, null=True, default=None)
    posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Posted Balance does not include pending debits.",
    )
    available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Available Balance has pending debits deducted.",
    )
    unallocated_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Amount of money that is not allocated to any budget.",
    )


########################################################################
########################################################################
#
# NOTE: we must make sure that there is always a 'safe to spend'
# budget. It is displayed somewhat specially.
#
class Budget(MoneyPoolBaseClass):
    """"""

    #####################################################################
    #
    class BudgetType(DjangoChoices):
        """
        Goal -> money accumulates and once it reaches the target_balance
                the goal is complete (and further automatic accumulation
                of money does not happen.)

        Recurring -> money accumulates and once it reaches the
                target_balance it is complete. However, if the amount of
                money in the budget falls below the target_balance, it
                will start accuring money again on its schedule.
        """

        goal = ChoiceItem("G", "Goal")
        recurring_to_goal = ChoiceItem("R", "Recurring to Goal")
        recurring_w_fillup_goal = ChoiceItem("F", "Recurring to Fill-up Goal")
        associated_fillup_goal = ChoiceItem("A", "Associated Fill-up Goal")

    #
    #####################################################################

    #####################################################################
    #
    class FundingType(DjangoChoices):
        """
        How is a budget funded? Budgets are credited some time on the day
        of their specified funding schedule. How much money is
        credited in to a budget is of tehse types:

        Target Date -> You want the goal to be funded by the target
            date. (the amount left to fund the budget divided by the
            number of days in the funding schedule before the target
            date)

        Fixed Amount -> You want the goal to be credited a fixed
            amount on its funding schedule dates.
        """

        target_date = ChoiceItem("D", "Target Date")
        fixed_amount = ChoiceItem("F", "Fixed Amount")

    #
    #####################################################################

    name = models.CharField(max_length=200)
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)
    balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
    )
    target_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
    )

    budget_type = models.CharField(
        max_length=1, choices=BudgetType.choices, default=BudgetType.goal
    )

    # Only relevant if the FundingType is 'target_date'
    #
    target_date = models.DateTimeField(null=True, blank=True)

    # Only relevant if the BudgetType is 'recurring'
    #
    with_fillup_goal = models.BooleanField(default=False)

    # Only relevant if the BudgetType is 'recurring' and
    # 'with_fillup_goal' is True. The fillup_goal is automatically
    # created with a fixed naming pattern based on the name of this
    # recurring budget.
    #
    fillup_goal = models.ForeignKey("self", null=True)

    archived = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    paused = models.BooleanField(
        default=False,
        description="A paused budget does not get automatically funded on its schedule.",
    )
    funding_schedule = recurrence.fields.RecurrenceField()

    # Only relevant for 'recurring' budgets
    #
    recurrance_schedule = recurrence.fields.RecurrenceField(null=True)

    image = models.ImageField(
        upload_to="budget_images/%Y-%m-%d/",
        height_field="image_height",
        width_field="image_width",
        null=True,
        blank=True,
    )
    image_height = models.IntegerField()
    image_width = models.IntegerField()
    memo = models.TextField(max_length=512, null=True, blank=True)
    # auto-spend - ManyToManyField - but only one budget can per bank
    # account can have an auto-spend category asigned to it.


TRANSACTION_CATEGORY_CHOICES = (
    ("Business:Business Clothing", "Business Clothing"),
    ("Business:Business Services", "Business Services"),
    ("Business:Business Supplies", "Business Supplies"),
    ("Business:Meals", "Meals"),
    ("Business:Travel", "Travel"),
    ("Children:Activities", "Activities"),
    ("Children:Allowance", "Allowance"),
    ("Children:Baby Supplies", "Baby Supplies"),
    ("Children:Childcare", "Childcare"),
    ("Children:Kids Clothing", "Kids Clothing"),
    ("Children:Kids Education", "Kids Education"),
    ("Children:Toys", "Toys"),
    ("Culture:Art", "Art"),
    ("Culture:Books", "Books"),
    ("Culture:Dance", "Dance"),
    ("Culture:Games", "Games"),
    ("Culture:Movies", "Movies"),
    ("Culture:Music", "Music"),
    ("Culture:News", "News"),
    ("Culture:Random Fun", "Random Fun"),
    ("Culture:TV", "TV"),
    ("Education:Books & Supplies", "Books & Supplies"),
    ("Education:Room & Board", "Room & Board"),
    ("Education:Student Loans", "Student Loans"),
    ("Education: Tuition & Fees", " Tuition & Fees"),
    ("Fees:ATM Fees", "ATM Fees"),
    ("Fees:Investment Fees", "Investment Fees"),
    ("Fees:Other Fees", "Other Fees"),
    ("Financial:Accounting", "Accounting"),
    ("Financial:Credit Card Payment", "Credit Card Payment"),
    ("Financial:Financial Advice", "Financial Advice"),
    ("Financial:Life Insurance", "Life Insurance"),
    ("Financial:Loan", "Loan"),
    ("Financial:Loan Payment", "Loan Payment"),
    ("Financial:Money Transfers", "Money Transfers"),
    ("Financial:Other Financial", "Other Financial"),
    ("Financial:Tax Preparation", "Tax Preparation"),
    ("Financial:Taxes, Federal", "Taxes, Federal"),
    ("Financial:Taxes, Other", "Taxes, Other"),
    ("Financial:Taxes, State", "Taxes, State"),
    ("Food & Drink:Alcohol & Bars", "Alcohol & Bars"),
    ("Food & Drink:Coffee & Tea", "Coffee & Tea"),
    ("Food & Drink:Dessert", "Dessert"),
    ("Food & Drink:Fast Food", "Fast Food"),
    ("Food & Drink:Groceries", "Groceries"),
    ("Food & Drink:Other Food & Drink", "Other Food & Drink"),
    ("Food & Drink:Restaurants", "Restaurants"),
    ("Food & Drink:Snacks", "Snacks"),
    ("Food & Drink:Tobacco & Like", "Tobacco & Like"),
    ("Gifts & Donations:Charities", "Charities"),
    ("Gifts & Donations:Gifts", "Gifts"),
    ("Health & Medical:Care Facilities", "Care Facilities"),
    ("Health & Medical:Dentist", "Dentist"),
    ("Health & Medical:Doctor", "Doctor"),
    ("Health & Medical:Equipment", "Equipment"),
    ("Health & Medical:Eyes", "Eyes"),
    ("Health & Medical:Health Insurance", "Health Insurance"),
    ("Health & Medical:Other Health & Medical", "Other Health & Medical"),
    ("Health & Medical:Pharmacies", "Pharmacies"),
    ("Health & Medical:Prescriptions", "Prescriptions"),
    ("Home:Furnishings", "Furnishings"),
    ("Home:Home Insurance", "Home Insurance"),
    ("Home:Home Purchase", "Home Purchase"),
    ("Home:Home Services", "Home Services"),
    ("Home:Home Supplies", "Home Supplies"),
    ("Home:Lawn & Garden", "Lawn & Garden"),
    ("Home:Mortgage", "Mortgage"),
    ("Home:Moving", "Moving"),
    ("Home:Other Home", "Other Home"),
    ("Home:Property Tax", "Property Tax"),
    ("Home:Rent", "Rent"),
    ("Home:Renter's Insurance", "Renter's Insurance"),
    ("Income:Bonus", "Bonus"),
    ("Income:Commission", "Commission"),
    ("Income:Interest", "Interest"),
    ("Income:Other Income", "Other Income"),
    ("Income:Paycheck", "Paycheck"),
    ("Income:Reimbursement", "Reimbursement"),
    ("Income:Rental Income", "Rental Income"),
    ("Investment:Education Investment", "Education Investment"),
    ("Investment:Other Investments", "Other Investments"),
    ("Investment:Retirement", "Retirement"),
    ("Investment:Stocks & Mutual Funds", "Stocks & Mutual Funds"),
    ("Legal:Legal Fees", "Legal Fees"),
    ("Legal:Legal Services", "Legal Services"),
    ("Legal:Other Legal Costs", "Other Legal Costs"),
    ("Office:Equipment", "Equipment"),
    ("Office:Office Supplies", "Office Supplies"),
    ("Office:Other Office", "Other Office"),
    ("Office:Postage & Shipping", "Postage & Shipping"),
    ("Personal:Accessories", "Accessories"),
    ("Personal:Beauty", "Beauty"),
    ("Personal:Body Enhancement", "Body Enhancement"),
    ("Personal:Clothing", "Clothing"),
    ("Personal:Counseling", "Counseling"),
    ("Personal:Hair", "Hair"),
    ("Personal:Hobbies", "Hobbies"),
    ("Personal:Jewelry", "Jewelry"),
    ("Personal:Laundry", "Laundry"),
    ("Personal:Other Personal", "Other Personal"),
    ("Personal:Religion", "Religion"),
    ("Personal:Shoes", "Shoes"),
    ("Pets:Pet Food", "Pet Food"),
    ("Pets:Pet Grooming", "Pet Grooming"),
    ("Pets:Pet Medicine", "Pet Medicine"),
    ("Pets:Pet Supplies", "Pet Supplies"),
    ("Pets:Veterinarian", "Veterinarian"),
    ("Sports & Fitness:Camping", "Camping"),
    ("Sports & Fitness:Fitness Gear", "Fitness Gear"),
    ("Sports & Fitness:Golf", "Golf"),
    ("Sports & Fitness:Memberships", "Memberships"),
    ("Sports & Fitness:Other Sports & Fitness", "Other Sports & Fitness"),
    ("Sports & Fitness:Sporting Events", "Sporting Events"),
    ("Sports & Fitness:Sporting Goods", "Sporting Goods"),
    ("Technology:Domains & Hosting", "Domains & Hosting"),
    ("Technology:Hardware", "Hardware"),
    ("Technology:Online Services", "Online Services"),
    ("Technology:Software", "Software"),
    ("Transportation:Auto Insurance", "Auto Insurance"),
    ("Transportation:Auto Payment", "Auto Payment"),
    ("Transportation:Auto Services", "Auto Services"),
    ("Transportation:Auto Supplies", "Auto Supplies"),
    ("Transportation:Bicycle", "Bicycle"),
    ("Transportation:Boats & Marine", "Boats & Marine"),
    ("Transportation:Gas", "Gas"),
    ("Transportation:Other Transportation", "Other Transportation"),
    ("Transportation:Parking & Tolls", "Parking & Tolls"),
    ("Transportation:Parking Tickets", "Parking Tickets"),
    ("Transportation:Public Transit", "Public Transit"),
    ("Transportation:Shipping", "Shipping"),
    ("Transportation:Taxies", "Taxies"),
    ("Travel:Car Rental", "Car Rental"),
    ("Travel:Flights", "Flights"),
    ("Travel:Hotels", "Hotels"),
    ("Travel:Tours & Cruises", "Tours & Cruises"),
    ("Travel:Train", "Train"),
    ("Travel:Travel Buses", "Travel Buses"),
    ("Travel:Travel Dining", "Travel Dining"),
    ("Travel:Travel Entertainment", "Travel Entertainment"),
    ("Uncategorized:Cash", "Cash"),
    ("Uncategorized:Other Shopping", "Other Shopping"),
    ("Uncategorized:Unknown", "Unknown"),
    ("Utilities:Cable", "Cable"),
    ("Utilities:Electricity", "Electricity"),
    ("Utilities:Gas & Fuel", "Gas & Fuel"),
    ("Utilities:Internet", "Internet"),
    ("Utilities:Other Utilities", "Other Utilities"),
    ("Utilities:Phone", "Phone"),
    ("Utilities:Trash", "Trash"),
    ("Utilities:Water & Sewer", "Water & Sewer"),
)


########################################################################
########################################################################
#
class TransactionBaseClass(MoneyPoolBaseClass):
    amount = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
    )
    bank_account = models.ForeignKey(BankAccount, on_delete=models.CASCADE)

    class Meta:
        abstract = True


########################################################################
########################################################################
#
class ThirdPartyTransaction(TransactionBaseClass):
    """
    A transaction detailing a credit/debit from some 3rd party

    NOTE: if this is associated with a budget, deleting the budget
    moves it back to the 'safe to spend' budget.
    """

    #####################################################################
    #
    class TransactionType(DjangoChoices):
        """
        An extended list of transaction types based on the original data
        in our existing bank accounts downloaded transaction logs.
        """

        signature_purchase = ChoiceItem(
            "signature_purchase", "Signature Purchase"
        )
        ach = ChoiceItem("ach", "ACH")
        round_up_transfer = ChoiceItem("round-up_transfer", "Round-up Transfer")
        protected_goal_account_transfer = ChoiceItem(
            "protected_goal_account_transfer", "Protected Goal Account Transfer"
        )
        fee = ChoiceItem("fee", "Fee")
        pin_purchase = ChoiceItem("pin_purchase", "Pin Purchase")
        signature_credit = ChoiceItem("signature_credit", "Signature Credit")
        interest_credit = ChoiceItem("interest_credit", "Interest Credit")
        shared_transfer = ChoiceItem("shared_transfer", "Shared Transfer")
        courtesy_credit = ChoiceItem("courtesy_credit", "Courtesy Credit")
        atm_withdrawal = ChoiceItem("atm_withdrawal", "ATM Withdrawal")
        bill_payment = ChoiceItem("bill_payment", "Bill Payment")
        bank_generated_credit = ChoiceItem(
            "bank_generated_credit", "Bank Generated Credit"
        )
        wire_transfer = ChoiceItem("wire_transfer", "Wire Transfer")
        check_deposit = ChoiceItem("check_deposit", "Check Deposit")
        c2c = ChoiceItem("c2c", "c2c")
        migration_interbank_transfer = ChoiceItem(
            "Migration Interbank Transfer", "migration_interbank_transfer"
        )
        balance_sweep = ChoiceItem("balance_sweep", "Balance Sweep")
        ach_reversal = ChoiceItem("ach_reversal", "ACH Reversal")
        adjustment = ChoiceItem("adjustment", "Adjustment")
        signature_return = ChoiceItem("signature_return", "Signature return")
        not_set = ChoiceItem("", "--------")

    #
    #####################################################################

    party = models.CharField(max_length=300, null=True, blank=True)
    transaction_date = models.DateTimeField(null=False)
    transaction_type = models.CharField(
        length=32, choices=TransactionType.choices
    )
    pending = models.BooleanField(default=False)
    memo = models.TextField(max_length=512, null=True, blank=True)
    raw_description = models.TextField(max_length=512)
    description = models.TextField(max_length=512, null=True, blank=True)
    budget = models.ForeignKey("Budget")
    account_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Posted Balance does not include pending debits.",
    )
    account_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Available Balance has pending debits deducted.",
    )
    budget_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Posted Balance does not include pending debits.",
    )
    budget_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Available Balance has pending debits deducted.",
    )
    # XXX Probably should make category its own object class and
    #     pre-create a bunch of those in the initial migration.
    #
    category = models.CharField(
        max_length=64,
        choices=TRANSACTION_CATEGORY_CHOICES,
        # default="Uncategorized:Unknown",
    )
    image = models.ImageField(
        upload_to="transaction_images/%Y-%m-%d/",
        height_field="image_height",
        width_field="image_width",
        null=True,
        blank=True,
    )
    image_height = models.IntegerField()
    image_width = models.IntegerField()
    document = models.FileField(
        upload_to="transaction_documents/%Y-%m-%d/", null=True, blank=True
    )


########################################################################
########################################################################
#
class InternalTransaction(TransactionBaseClass):
    """
    An internal transaction moving money between budgets
    """

    src_budget = models.ForeignKey("Budget", null=False)
    dest_budget = models.ForiegnKey("Budget", null=False)
    actor = models.ForeignKey("User", null=False)
    src_budget_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Posted Balance does not include pending debits.",
    )
    src_budget_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Available Balance has pending debits deducted.",
    )
    dst_budget_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Posted Balance does not include pending debits.",
    )
    dst_budget_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        description="Available Balance has pending debits deducted.",
    )

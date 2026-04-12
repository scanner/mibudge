import uuid
from typing import Any

import recurrence.fields
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from djmoney.models.fields import MoneyField
from djmoney.money import Money
from encrypted_fields.fields import EncryptedCharField

User = get_user_model()

# https://stackoverflow.com/questions/224462/storing-money-in-a-decimal-column-what-precision-and-scale/224866#224866
#
MAX_DIGITS = 14
DECIMAL_PLACES = 2


####################################################################
#
def get_default_currency() -> str:
    """Return the project-wide default currency from settings.

    Used as a callable default for MoneyField 'default_currency' and
    CharField defaults so that changing DEFAULT_CURRENCY in settings
    does not generate new migrations.
    """
    return settings.DEFAULT_CURRENCY


####################################################################
#
def get_default_zero() -> Money:
    """Return a zero Money value in the project-wide default currency.

    Used as a callable default for MoneyField 'default' so that both
    'default' and 'default_currency' are callables -- a requirement
    of django-money when 'default_currency' is callable.
    """
    return Money("0.00", settings.DEFAULT_CURRENCY)


########################################################################
########################################################################
#
class MoneyPoolBaseClass(models.Model):
    # NOTE: We are using UUID's as pseudo-primary keys.  This was originally
    # because some of the data we import from simple bank json files has UUID's
    # as identifiers and I thought it best to leverage that in my models and
    # continue to use UUID's.. but without some of the tradeoffs of UUID's as
    # primary keys.
    #
    # See: https://www.stevenmoseley.com/blog/tech/uuid-primary-keys-django-rest-framework-2-steps
    #
    pkid = models.BigAutoField(primary_key=True, editable=False)
    id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
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

    def __str__(self) -> str:
        return self.name

    # XXX Add a validator to make sure only digits are used
    routing_number = models.CharField(
        max_length=9, null=True, default=None, editable=False, unique=True
    )

    # ISO 4217 currency code.  Bank accounts created under this bank
    # inherit this currency by default.
    #
    default_currency = models.CharField(
        max_length=3,
        default=get_default_currency,
        help_text="ISO 4217 currency code (e.g. USD, EUR, GBP).",
    )


########################################################################
########################################################################
#
class BankAccount(MoneyPoolBaseClass):
    """
    This app is about budgeting your money but as a view in to your
    bank account's money. Thus the fundamental aspect of a Budget is
    which bank account it is tied to.
    """

    #####################################################################
    #
    class BankAccountType(models.TextChoices):
        CHECKING = "C", "Checking"
        SAVINGS = "S", "Savings"
        CREDIT_CARD = "X", "Credit Card"

    #
    #####################################################################

    name = models.CharField(max_length=200)
    bank = models.ForeignKey(
        Bank, to_field="id", on_delete=models.CASCADE, editable=False
    )
    owners: "models.ManyToManyField[Any, Any]" = models.ManyToManyField(User)
    group = models.ForeignKey(
        "auth.Group",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Joint ownership group for this account.",
    )

    # XXX Add a validator to make sure only digits are used
    account_number = EncryptedCharField(
        max_length=12, null=True, blank=True, default=None, unique=True
    )

    account_type = models.CharField(
        max_length=1,
        choices=BankAccountType.choices,
        default=BankAccountType.CHECKING,
    )

    # ISO 4217 currency code for this account.  Specified by the user
    # on creation; defaults to the bank's default_currency if omitted.
    # Immutable after creation -- the pre_save signal propagates this
    # to the balance MoneyField currencies.
    #
    currency = models.CharField(
        max_length=3,
        default=get_default_currency,
        help_text="ISO 4217 currency code (e.g. USD, EUR, GBP).",
    )

    # Available Balance is the amount available for withdrawal and may include
    # pending transactions not yet posted to your account.
    #
    # Posted Balance is the account's balance after items have posted to your
    # accounts as deposits or withdrawals.
    #
    posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        help_text="Posted Balance does not include pending debits.",
        editable=False,
    )
    available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        help_text="Available Balance has pending debits deducted.",
        editable=False,
    )

    # All the money in a bank account is split across all budgets in the bank
    # account. We need one budget that always exists that can not be
    # archived. This is the budget of money that has not been allocated to any
    # other budget.
    #
    # This budget is created if this foreign key is null in the bank account's
    # post_save signal.
    #
    unallocated_budget = models.ForeignKey(
        "Budget",
        models.SET_NULL,
        to_field="id",
        blank=True,
        null=True,
    )

    #####################################################################
    #
    def __str__(self) -> str:
        return f"{self.name} ({self.bank.name}) [{str(self.id)[:8]}]"


########################################################################
########################################################################
#
class TransactionCategory(models.TextChoices):
    BUSINESS_CLOTHING = "Business:Business Clothing", "Business Clothing"
    BUSINESS_SERVICES = "Business:Business Services", "Business Services"
    BUSINESS_SUPPLIES = "Business:Business Supplies", "Business Supplies"
    MEALS = "Business:Meals", "Meals"
    TRAVEL = "Business:Travel", "Travel"
    ACTIVITIES = "Children:Activities", "Activities"
    ALLOWANCE = "Children:Allowance", "Allowance"
    BABY_SUPPLIES = "Children:Baby Supplies", "Baby Supplies"
    CHILDCARE = "Children:Childcare", "Childcare"
    KIDS_CLOTHING = "Children:Kids Clothing", "Kids Clothing"
    KIDS_EDUCATION = "Children:Kids Education", "Kids Education"
    TOYS = "Children:Toys", "Toys"
    ART = "Culture:Art", "Art"
    BOOKS = "Culture:Books", "Books"
    DANCE = "Culture:Dance", "Dance"
    GAMES = "Culture:Games", "Games"
    MOVIES = "Culture:Movies", "Movies"
    MUSIC = "Culture:Music", "Music"
    NEWS = "Culture:News", "News"
    RANDOM_FUN = "Culture:Random Fun", "Random Fun"
    TV = "Culture:TV", "TV"
    BOOKS_SUPPLIES = "Education:Books & Supplies", "Books & Supplies"
    ROOM_BOARD = "Education:Room & Board", "Room & Board"
    STUDENT_LOANS = "Education:Student Loans", "Student Loans"
    TUITION_FEES = "Education: Tuition & Fees", " Tuition & Fees"
    ATM_FEES = "Fees:ATM Fees", "ATM Fees"
    INVESTMENT_FEES = "Fees:Investment Fees", "Investment Fees"
    OTHER_FEES = "Fees:Other Fees", "Other Fees"
    ACCOUNTING = "Financial:Accounting", "Accounting"
    CREDIT_CARD_PAYMENT = "Financial:Credit Card Payment", "Credit Card Payment"
    FINANCIAL_ADVICE = "Financial:Financial Advice", "Financial Advice"
    LIFE_INSURANCE = "Financial:Life Insurance", "Life Insurance"
    LOAN = "Financial:Loan", "Loan"
    LOAN_PAYMENT = "Financial:Loan Payment", "Loan Payment"
    MONEY_TRANSFERS = "Financial:Money Transfers", "Money Transfers"
    OTHER_FINANCIAL = "Financial:Other Financial", "Other Financial"
    TAX_PREPARATION = "Financial:Tax Preparation", "Tax Preparation"
    TAXES_FEDERAL = "Financial:Taxes, Federal", "Taxes, Federal"
    TAXES_OTHER = "Financial:Taxes, Other", "Taxes, Other"
    TAXES_STATE = "Financial:Taxes, State", "Taxes, State"
    ALCOHOL_BARS = "Food & Drink:Alcohol & Bars", "Alcohol & Bars"
    COFFEE_TEA = "Food & Drink:Coffee & Tea", "Coffee & Tea"
    DESSERT = "Food & Drink:Dessert", "Dessert"
    FAST_FOOD = "Food & Drink:Fast Food", "Fast Food"
    GROCERIES = "Food & Drink:Groceries", "Groceries"
    OTHER_FOOD_DRINK = "Food & Drink:Other Food & Drink", "Other Food & Drink"
    RESTAURANTS = "Food & Drink:Restaurants", "Restaurants"
    SNACKS = "Food & Drink:Snacks", "Snacks"
    TOBACCO_LIKE = "Food & Drink:Tobacco & Like", "Tobacco & Like"
    CHARITIES = "Gifts & Donations:Charities", "Charities"
    GIFTS = "Gifts & Donations:Gifts", "Gifts"
    CARE_FACILITIES = "Health & Medical:Care Facilities", "Care Facilities"
    DENTIST = "Health & Medical:Dentist", "Dentist"
    DOCTOR = "Health & Medical:Doctor", "Doctor"
    HEALTH_EQUIPMENT = "Health & Medical:Equipment", "Equipment"
    EYES = "Health & Medical:Eyes", "Eyes"
    HEALTH_INSURANCE = "Health & Medical:Health Insurance", "Health Insurance"
    OTHER_HEALTH_MEDICAL = (
        "Health & Medical:Other Health & Medical",
        "Other Health & Medical",
    )
    PHARMACIES = "Health & Medical:Pharmacies", "Pharmacies"
    PRESCRIPTIONS = "Health & Medical:Prescriptions", "Prescriptions"
    FURNISHINGS = "Home:Furnishings", "Furnishings"
    HOME_INSURANCE = "Home:Home Insurance", "Home Insurance"
    HOME_PURCHASE = "Home:Home Purchase", "Home Purchase"
    HOME_SERVICES = "Home:Home Services", "Home Services"
    HOME_SUPPLIES = "Home:Home Supplies", "Home Supplies"
    LAWN_GARDEN = "Home:Lawn & Garden", "Lawn & Garden"
    MORTGAGE = "Home:Mortgage", "Mortgage"
    MOVING = "Home:Moving", "Moving"
    OTHER_HOME = "Home:Other Home", "Other Home"
    PROPERTY_TAX = "Home:Property Tax", "Property Tax"
    RENT = "Home:Rent", "Rent"
    RENTERS_INSURANCE = "Home:Renter's Insurance", "Renter's Insurance"
    BONUS = "Income:Bonus", "Bonus"
    COMMISSION = "Income:Commission", "Commission"
    INTEREST = "Income:Interest", "Interest"
    OTHER_INCOME = "Income:Other Income", "Other Income"
    PAYCHECK = "Income:Paycheck", "Paycheck"
    REIMBURSEMENT = "Income:Reimbursement", "Reimbursement"
    RENTAL_INCOME = "Income:Rental Income", "Rental Income"
    EDUCATION_INVESTMENT = (
        "Investment:Education Investment",
        "Education Investment",
    )
    OTHER_INVESTMENTS = "Investment:Other Investments", "Other Investments"
    RETIREMENT = "Investment:Retirement", "Retirement"
    STOCKS_MUTUAL_FUNDS = (
        "Investment:Stocks & Mutual Funds",
        "Stocks & Mutual Funds",
    )
    LEGAL_FEES = "Legal:Legal Fees", "Legal Fees"
    LEGAL_SERVICES = "Legal:Legal Services", "Legal Services"
    OTHER_LEGAL_COSTS = "Legal:Other Legal Costs", "Other Legal Costs"
    OFFICE_EQUIPMENT = "Office:Equipment", "Equipment"
    OFFICE_SUPPLIES = "Office:Office Supplies", "Office Supplies"
    OTHER_OFFICE = "Office:Other Office", "Other Office"
    POSTAGE_SHIPPING = "Office:Postage & Shipping", "Postage & Shipping"
    ACCESSORIES = "Personal:Accessories", "Accessories"
    BEAUTY = "Personal:Beauty", "Beauty"
    BODY_ENHANCEMENT = "Personal:Body Enhancement", "Body Enhancement"
    CLOTHING = "Personal:Clothing", "Clothing"
    COUNSELING = "Personal:Counseling", "Counseling"
    HAIR = "Personal:Hair", "Hair"
    HOBBIES = "Personal:Hobbies", "Hobbies"
    JEWELRY = "Personal:Jewelry", "Jewelry"
    LAUNDRY = "Personal:Laundry", "Laundry"
    OTHER_PERSONAL = "Personal:Other Personal", "Other Personal"
    RELIGION = "Personal:Religion", "Religion"
    SHOES = "Personal:Shoes", "Shoes"
    PET_FOOD = "Pets:Pet Food", "Pet Food"
    PET_GROOMING = "Pets:Pet Grooming", "Pet Grooming"
    PET_MEDICINE = "Pets:Pet Medicine", "Pet Medicine"
    PET_SUPPLIES = "Pets:Pet Supplies", "Pet Supplies"
    VETERINARIAN = "Pets:Veterinarian", "Veterinarian"
    CAMPING = "Sports & Fitness:Camping", "Camping"
    FITNESS_GEAR = "Sports & Fitness:Fitness Gear", "Fitness Gear"
    GOLF = "Sports & Fitness:Golf", "Golf"
    MEMBERSHIPS = "Sports & Fitness:Memberships", "Memberships"
    OTHER_SPORTS_FITNESS = (
        "Sports & Fitness:Other Sports & Fitness",
        "Other Sports & Fitness",
    )
    SPORTING_EVENTS = "Sports & Fitness:Sporting Events", "Sporting Events"
    SPORTING_GOODS = "Sports & Fitness:Sporting Goods", "Sporting Goods"
    DOMAINS_HOSTING = "Technology:Domains & Hosting", "Domains & Hosting"
    HARDWARE = "Technology:Hardware", "Hardware"
    ONLINE_SERVICES = "Technology:Online Services", "Online Services"
    SOFTWARE = "Technology:Software", "Software"
    AUTO_INSURANCE = "Transportation:Auto Insurance", "Auto Insurance"
    AUTO_PAYMENT = "Transportation:Auto Payment", "Auto Payment"
    AUTO_SERVICES = "Transportation:Auto Services", "Auto Services"
    AUTO_SUPPLIES = "Transportation:Auto Supplies", "Auto Supplies"
    BICYCLE = "Transportation:Bicycle", "Bicycle"
    BOATS_MARINE = "Transportation:Boats & Marine", "Boats & Marine"
    GAS = "Transportation:Gas", "Gas"
    OTHER_TRANSPORTATION = (
        "Transportation:Other Transportation",
        "Other Transportation",
    )
    PARKING_TOLLS = "Transportation:Parking & Tolls", "Parking & Tolls"
    PARKING_TICKETS = "Transportation:Parking Tickets", "Parking Tickets"
    PUBLIC_TRANSIT = "Transportation:Public Transit", "Public Transit"
    SHIPPING = "Transportation:Shipping", "Shipping"
    TAXIES = "Transportation:Taxies", "Taxies"
    CAR_RENTAL = "Travel:Car Rental", "Car Rental"
    FLIGHTS = "Travel:Flights", "Flights"
    HOTELS = "Travel:Hotels", "Hotels"
    TOURS_CRUISES = "Travel:Tours & Cruises", "Tours & Cruises"
    TRAIN = "Travel:Train", "Train"
    TRAVEL_BUSES = "Travel:Travel Buses", "Travel Buses"
    TRAVEL_DINING = "Travel:Travel Dining", "Travel Dining"
    TRAVEL_ENTERTAINMENT = (
        "Travel:Travel Entertainment",
        "Travel Entertainment",
    )
    CASH = "Uncategorized:Cash", "Cash"
    OTHER_SHOPPING = "Uncategorized:Other Shopping", "Other Shopping"
    UNKNOWN = "Uncategorized:Unknown", "Unknown"
    UNASSIGNED = "Uncategorized:Unassigned", "-------"
    CABLE = "Utilities:Cable", "Cable"
    ELECTRICITY = "Utilities:Electricity", "Electricity"
    GAS_FUEL = "Utilities:Gas & Fuel", "Gas & Fuel"
    INTERNET = "Utilities:Internet", "Internet"
    OTHER_UTILITIES = "Utilities:Other Utilities", "Other Utilities"
    PHONE = "Utilities:Phone", "Phone"
    TRASH = "Utilities:Trash", "Trash"
    WATER_SEWER = "Utilities:Water & Sewer", "Water & Sewer"

    @property
    def group(self) -> str:
        """The top-level category group (e.g. 'Business', 'Food & Drink')."""
        return self.value.split(":")[0]

    @property
    def display_name(self) -> str:
        """The sub-category name portion of the value (e.g. 'Business Clothing')."""
        return self.value.split(":")[1]


########################################################################
########################################################################
#
# NOTE: we must make sure that there is always a 'safe to spend'
# budget. It is displayed somewhat specially.
#
class Budget(MoneyPoolBaseClass):
    """
    The core of the MoneyPools system is the budget. Modeled somewhat
    after what Simple Bank expressed as "goals" and "expenses" but
    tweaked for how we actually used these systems with more
    automation around recurring budgets (what Simple called
    "expenses") and non-recurring budgets (ie: "Goals") and whether or
    not they had a budget that money was filled up on completion of a
    recurring budget.
    """

    #####################################################################
    #
    class BudgetType(models.TextChoices):
        """
        Goal -> money accumulates and once it reaches the target_balance
                the goal is complete (and further automatic accumulation
                of money does not happen.)

        Recurring -> money accumulates and once it reaches the
                target_balance it is complete. However, if the amount of
                money in the budget falls below the target_balance, it
                will start accuring money again on its schedule.
        """

        GOAL = "G", "Goal"
        RECURRING = "R", "Recurring"
        ASSOCIATED_FILLUP_GOAL = "A", "Associated Fill-up Goal"

    #
    #####################################################################

    #####################################################################
    #
    class FundingType(models.TextChoices):
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

        TARGET_DATE = "D", "Target Date"
        FIXED_AMOUNT = "F", "Fixed Amount"

    #
    #####################################################################

    name = models.CharField(max_length=200)
    bank_account = models.ForeignKey(
        BankAccount, to_field="id", on_delete=models.CASCADE, editable=False
    )
    balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
    )
    target_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
    )
    budget_type = models.CharField(
        max_length=1,
        choices=BudgetType.choices,
        default=BudgetType.GOAL,
    )
    funding_type = models.CharField(
        max_length=1,
        choices=FundingType.choices,
        default=FundingType.TARGET_DATE,
    )

    # Only relevant if the FundingType is 'target_date'
    #
    target_date = models.DateField(null=True, blank=True)

    # Only relevant if the BudgetType is 'recurring'
    #
    with_fillup_goal = models.BooleanField(default=False)

    # Only relevant if the BudgetType is 'recurring' and 'with_fillup_goal' is
    # True. The fillup_goal is automatically created with a fixed naming
    # pattern based on the name of this recurring budget.
    #
    # This is tied with the `recurrence_schedule` for the budget. On the
    # reccurence schedule date money is moved from the recurring goal to the
    # fillup_goal. Also NOTE: The fillup goal is called this because "it is
    # filled up" to the target amoung on this budget that points to the fillup
    # goal. Any remainder is left in this budget. So, for example: If this
    # recurring budget has a target balance of $100 and the associated
    # fillup_goal budget has $15 in it then on the recurrence schedule date
    # $85 will be transferred from the recurring budget to the fillup goal
    # budget (filling up the fillup_goal budget), leaving $15 in the source
    # recurring budget.
    #
    fillup_goal = models.ForeignKey(
        "self", to_field="id", null=True, on_delete=models.CASCADE
    )

    archived = models.BooleanField(default=False, editable=False)
    archived_at = models.DateTimeField(null=True, blank=True, editable=False)
    paused = models.BooleanField(
        default=False,
        help_text="A paused budget does not get automatically funded on its schedule.",
    )
    funding_schedule = recurrence.fields.RecurrenceField()

    # Only relevant for 'recurring' budgets with FundingType target_date.
    # This is the interval at which we need this budget to be completed. So,
    # if you have a bill you need to pay once a month, by the first of the
    # month you would set your recurrence schedule to be "by the last day of
    # each month." Things like rent, regular payments, etc. Another example is
    # if you have a service you subscribe to that is renewed every year.. you
    # would set the recurrence schedule to be shortly before that subscription
    # is due.
    #
    recurrance_schedule = recurrence.fields.RecurrenceField(null=True)

    image = models.ImageField(
        upload_to="budget_images/%Y-%m-%d/",
        height_field="image_height",
        width_field="image_width",
        null=True,
        blank=True,
    )
    image_height = models.IntegerField(null=True, editable=False, blank=True)
    image_width = models.IntegerField(null=True, editable=False, blank=True)
    memo = models.TextField(max_length=512, null=True, blank=True)

    # NOTE: Need to enforce in pre-save that only one budget in an
    #       account has the given fields selected.
    #
    auto_spend = models.JSONField(default=list, blank=True)


########################################################################
########################################################################
#
class TransactionBaseClass(MoneyPoolBaseClass):
    amount = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        editable=False,
    )
    bank_account = models.ForeignKey(
        BankAccount, to_field="id", on_delete=models.CASCADE, editable=False
    )

    class Meta:
        abstract = True


########################################################################
########################################################################
#
class Transaction(TransactionBaseClass):
    """
    A transaction detailing a credit/debit from some 3rd party

    NOTE: if this is associated with a budget, deleting the budget
    moves it back to the 'unallocated' budget.
    """

    #####################################################################
    #
    class TransactionType(models.TextChoices):
        """
        An extended list of transaction types based on the original data
        in our existing bank accounts downloaded transaction logs.
        """

        SIGNATURE_PURCHASE = "signature_purchase", "Signature Purchase"
        ACH = "ach", "ACH"
        ROUND_UP_TRANSFER = "round-up_transfer", "Round-up Transfer"
        PROTECTED_GOAL_ACCOUNT_TRANSFER = (
            "protected_goal_account_transfer",
            "Protected Goal Account Transfer",
        )
        FEE = "fee", "Fee"
        PIN_PURCHASE = "pin_purchase", "Pin Purchase"
        SIGNATURE_CREDIT = "signature_credit", "Signature Credit"
        INTEREST_CREDIT = "interest_credit", "Interest Credit"
        SHARED_TRANSFER = "shared_transfer", "Shared Transfer"
        COURTESY_CREDIT = "courtesy_credit", "Courtesy Credit"
        ATM_WITHDRAWAL = "atm_withdrawal", "ATM Withdrawal"
        BILL_PAYMENT = "bill_payment", "Bill Payment"
        BANK_GENERATED_CREDIT = (
            "bank_generated_credit",
            "Bank Generated Credit",
        )
        WIRE_TRANSFER = "wire_transfer", "Wire Transfer"
        CHECK_DEPOSIT = "check_deposit", "Check Deposit"
        CHECK = "check", "Check"
        C2C = "c2c", "c2c"
        MIGRATION_INTERBANK_TRANSFER = (
            "migration_interbank_transfer",
            "Migration Interbank Transfer",
        )
        BALANCE_SWEEP = "balance_sweep", "Balance Sweep"
        ACH_REVERSAL = "ach_reversal", "ACH Reversal"
        ADJUSTMENT = "adjustment", "Adjustment"
        SIGNATURE_RETURN = "signature_return", "Signature return"
        FX_ORDER = "fx_order", "FX Order"
        NOT_SET = "", "--------"

    #
    #####################################################################

    # TODO: The `party` field is something that is derived from the
    # description in post processing after the Transaction has been
    # created. The desire is to have this be a foreign key relation or a set
    # of standardized names so we can easily say "all transactions by this
    # party"
    #
    party = models.CharField(
        max_length=300, null=True, blank=True, editable=False
    )
    transaction_date = models.DateTimeField(null=False, editable=False)
    transaction_type = models.CharField(
        max_length=32, choices=TransactionType.choices
    )

    # `pending` is a state we get from the bank. It basically means that the
    # amount may change until the state changes from `pending` to
    # `posted`. Also the `posted`
    #
    # The `available_balance` will always update with the amount of this
    # transaction. The `posted_balance` will only update when the transaction
    # is no longer pending.
    #
    # XXX Since `posted` is the final state maybe this should be `posted`
    #     instead of `pending` and we reverse the logic on when to apply it to
    #     the `posted_balance`. At least then the names all match where as now
    #     `pending` means `affects available` and `posted` means `affects
    #     available and posted `
    #
    pending = models.BooleanField(default=False, editable=False)
    memo = models.TextField(max_length=512, null=True, blank=True)
    raw_description = models.TextField(max_length=512, editable=False)

    # TODO: Initial value of the description is a cleaned up version of the
    #       raw_description. It is added in post processing at the same time
    #       that `party` is derived. Initially it is set to the same value as
    #       'raw_description'
    #
    # NOTE: this is filled in via the pre_save signal in ./signals.py
    #
    description = models.TextField(max_length=512)

    # Linked counterpart on another account. For example, a credit card
    # payment appears as a debit on checking and a credit on the card.
    # Populated opportunistically by the import pipeline when both sides
    # are present. Never required.
    #
    linked_transaction = models.OneToOneField(
        "self",
        to_field="id",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="linked_from",
    )

    # Budget assignment is handled through TransactionAllocation objects.
    # A non-split transaction has one allocation; a split transaction has
    # multiple allocations whose amounts sum to the transaction amount.
    bank_account_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        help_text="Posted Balance does not include pending debits.",
        editable=False,
    )
    bank_account_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        help_text="Available Balance has pending debits deducted.",
        editable=False,
    )
    image = models.ImageField(
        upload_to="transaction_images/%Y-%m-%d/",
        height_field="image_height",
        width_field="image_width",
        null=True,
        blank=True,
    )
    image_height = models.IntegerField(null=True, editable=False, blank=True)
    image_width = models.IntegerField(null=True, editable=False, blank=True)
    document = models.FileField(
        upload_to="transaction_documents/%Y-%m-%d/", null=True, blank=True
    )


########################################################################
########################################################################
#
class InternalTransaction(TransactionBaseClass):
    """
    An internal transacation is moving money between budgets. It is
    all within the same bank account so the bank account's balance
    never changes.

    There is no 'pending' status either. This is typically a user
    initiated action and it is basically final. You make the internal
    transaction and money is debited from one budget and credited in
    another budget.

    We support having the amount of the transaction changed, and even
    having the transaction deleted to update the associated budgets'
    balances (this is done using django signals.. so note well: bulk
    deleting of transactions will not update budget accounts so if you
    are going to delete multiple internal transactions you need to
    delete them one by one.)
    """

    # The src and dst budgets are not editable. The internal
    # transaction is created and the balances on the related budgets
    # are immediately modified in the pre_save hook. If the actor
    # wishes to change the amounts in the src and dst budgets again
    # they will create a new internal transaction doing just that. Not
    # editing an internal transaction that has already been created.
    #
    # You might describe these as "write once" objects.
    #
    src_budget = models.ForeignKey(
        Budget,
        to_field="id",
        on_delete=models.CASCADE,
        editable=False,
        related_name="budget_debits",
    )
    dst_budget = models.ForeignKey(
        Budget,
        to_field="id",
        on_delete=models.CASCADE,
        editable=False,
        related_name="budget_credits",
    )
    actor = models.ForeignKey(User, on_delete=models.CASCADE, editable=False)
    src_budget_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        editable=False,
    )
    dst_budget_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        editable=False,
    )


########################################################################
########################################################################
#
class TransactionAllocation(MoneyPoolBaseClass):
    """
    Maps a portion of a transaction's amount to a budget.

    Every transaction has at least one allocation. A non-split transaction
    has exactly one allocation whose amount equals the transaction amount.
    A split transaction has multiple allocations whose amounts sum to the
    transaction amount.

    Budget balance adjustments flow through allocations, not through the
    Transaction model directly. This gives a single code path for both
    split and non-split transactions.
    """

    transaction = models.ForeignKey(
        Transaction,
        to_field="id",
        on_delete=models.CASCADE,
        related_name="allocations",
        editable=False,
    )
    budget = models.ForeignKey(
        Budget,
        models.SET_NULL,
        to_field="id",
        null=True,
        related_name="transaction_allocations",
    )
    amount = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        editable=False,
    )
    budget_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=get_default_zero,
        default_currency=get_default_currency,
        editable=False,
    )
    # What this portion of the transaction was spent on. Lives here
    # rather than on Transaction because a single purchase (e.g. Costco)
    # can contain groceries and home supplies allocated to different
    # budgets with different categories.
    #
    # XXX Probably should make category its own object class and
    #     pre-create a bunch of those in the initial migration.
    #
    category = models.CharField(
        max_length=64,
        choices=TransactionCategory.choices,
        default=TransactionCategory.UNASSIGNED,
    )
    memo = models.TextField(max_length=512, null=True, blank=True)

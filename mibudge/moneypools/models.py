import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models

from djchoices import ChoiceItem, DjangoChoices
from djmoney.models.fields import MoneyField
from multiselectfield import MultiSelectField
import recurrence.fields

User = get_user_model()

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
    routing_number = models.CharField(
        max_length=9, null=True, default=None, editable=False, unique=True
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
    class BankAccountType(DjangoChoices):
        checking = ChoiceItem("C", "Checking")
        savings = ChoiceItem("S", "Savings")

    #
    #####################################################################

    name = models.CharField(max_length=200)
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, editable=False)
    owners = models.ManyToManyField(User)

    # XXX Add a validator to make sure only digits are used
    account_number = models.CharField(
        max_length=12, null=True, default=None, editable=False, unique=True
    )

    account_type = models.CharField(
        max_length=1,
        choices=BankAccountType.choices,
        default=BankAccountType.checking,
    )
    posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Posted Balance does not include pending debits.",
        editable=False,
    )
    available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Available Balance has pending debits deducted.",
        editable=False,
    )
    unallocated_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Amount of money that is not allocated to any budget.",
        editable=False,
    )


########################################################################
########################################################################
#
class TransactionCategory(DjangoChoices):
    business_clothing = ChoiceItem(
        "Business:Business Clothing", "Business Clothing"
    )
    business_services = ChoiceItem(
        "Business:Business Services", "Business Services"
    )
    business_supplies = ChoiceItem(
        "Business:Business Supplies", "Business Supplies"
    )
    meals = ChoiceItem("Business:Meals", "Meals")
    travel = ChoiceItem("Business:Travel", "Travel")
    activities = ChoiceItem("Children:Activities", "Activities")
    allowance = ChoiceItem("Children:Allowance", "Allowance")
    baby_supplies = ChoiceItem("Children:Baby Supplies", "Baby Supplies")
    childcare = ChoiceItem("Children:Childcare", "Childcare")
    kids_clothing = ChoiceItem("Children:Kids Clothing", "Kids Clothing")
    kids_education = ChoiceItem("Children:Kids Education", "Kids Education")
    toys = ChoiceItem("Children:Toys", "Toys")
    art = ChoiceItem("Culture:Art", "Art")
    books = ChoiceItem("Culture:Books", "Books")
    dance = ChoiceItem("Culture:Dance", "Dance")
    games = ChoiceItem("Culture:Games", "Games")
    movies = ChoiceItem("Culture:Movies", "Movies")
    music = ChoiceItem("Culture:Music", "Music")
    news = ChoiceItem("Culture:News", "News")
    random_fun = ChoiceItem("Culture:Random Fun", "Random Fun")
    tv = ChoiceItem("Culture:TV", "TV")
    books_supplies = ChoiceItem(
        "Education:Books & Supplies", "Books & Supplies"
    )
    room_board = ChoiceItem("Education:Room & Board", "Room & Board")
    student_loans = ChoiceItem("Education:Student Loans", "Student Loans")
    tuition_fees = ChoiceItem("Education: Tuition & Fees", " Tuition & Fees")
    atm_fees = ChoiceItem("Fees:ATM Fees", "ATM Fees")
    investment_fees = ChoiceItem("Fees:Investment Fees", "Investment Fees")
    other_fees = ChoiceItem("Fees:Other Fees", "Other Fees")
    accounting = ChoiceItem("Financial:Accounting", "Accounting")
    credit_card_payment = ChoiceItem(
        "Financial:Credit Card Payment", "Credit Card Payment"
    )
    financial_advice = ChoiceItem(
        "Financial:Financial Advice", "Financial Advice"
    )
    life_insurance = ChoiceItem("Financial:Life Insurance", "Life Insurance")
    loan = ChoiceItem("Financial:Loan", "Loan")
    loan_payment = ChoiceItem("Financial:Loan Payment", "Loan Payment")
    money_transfers = ChoiceItem("Financial:Money Transfers", "Money Transfers")
    other_financial = ChoiceItem("Financial:Other Financial", "Other Financial")
    tax_preparation = ChoiceItem("Financial:Tax Preparation", "Tax Preparation")
    taxes_federal = ChoiceItem("Financial:Taxes, Federal", "Taxes, Federal")
    taxes_other = ChoiceItem("Financial:Taxes, Other", "Taxes, Other")
    taxes_state = ChoiceItem("Financial:Taxes, State", "Taxes, State")
    alcohol_bars = ChoiceItem("Food & Drink:Alcohol & Bars", "Alcohol & Bars")
    coffee_tea = ChoiceItem("Food & Drink:Coffee & Tea", "Coffee & Tea")
    dessert = ChoiceItem("Food & Drink:Dessert", "Dessert")
    fast_food = ChoiceItem("Food & Drink:Fast Food", "Fast Food")
    groceries = ChoiceItem("Food & Drink:Groceries", "Groceries")
    other_food_drink = ChoiceItem(
        "Food & Drink:Other Food & Drink", "Other Food & Drink"
    )
    restaurants = ChoiceItem("Food & Drink:Restaurants", "Restaurants")
    snacks = ChoiceItem("Food & Drink:Snacks", "Snacks")
    tobacco_like = ChoiceItem("Food & Drink:Tobacco & Like", "Tobacco & Like")
    charities = ChoiceItem("Gifts & Donations:Charities", "Charities")
    gifts = ChoiceItem("Gifts & Donations:Gifts", "Gifts")
    care_facilities = ChoiceItem(
        "Health & Medical:Care Facilities", "Care Facilities"
    )
    dentist = ChoiceItem("Health & Medical:Dentist", "Dentist")
    doctor = ChoiceItem("Health & Medical:Doctor", "Doctor")
    equipment = ChoiceItem("Health & Medical:Equipment", "Equipment")
    eyes = ChoiceItem("Health & Medical:Eyes", "Eyes")
    health_insurance = ChoiceItem(
        "Health & Medical:Health Insurance", "Health Insurance"
    )
    other_health_medical = ChoiceItem(
        "Health & Medical:Other Health & Medical", "Other Health & Medical"
    )
    pharmacies = ChoiceItem("Health & Medical:Pharmacies", "Pharmacies")
    prescriptions = ChoiceItem(
        "Health & Medical:Prescriptions", "Prescriptions"
    )
    furnishings = ChoiceItem("Home:Furnishings", "Furnishings")
    home_insurance = ChoiceItem("Home:Home Insurance", "Home Insurance")
    home_purchase = ChoiceItem("Home:Home Purchase", "Home Purchase")
    home_services = ChoiceItem("Home:Home Services", "Home Services")
    home_supplies = ChoiceItem("Home:Home Supplies", "Home Supplies")
    lawn_garden = ChoiceItem("Home:Lawn & Garden", "Lawn & Garden")
    mortgage = ChoiceItem("Home:Mortgage", "Mortgage")
    moving = ChoiceItem("Home:Moving", "Moving")
    other_home = ChoiceItem("Home:Other Home", "Other Home")
    property_tax = ChoiceItem("Home:Property Tax", "Property Tax")
    rent = ChoiceItem("Home:Rent", "Rent")
    renters_insurance = ChoiceItem(
        "Home:Renter's Insurance", "Renter's Insurance"
    )
    bonus = ChoiceItem("Income:Bonus", "Bonus")
    commission = ChoiceItem("Income:Commission", "Commission")
    interest = ChoiceItem("Income:Interest", "Interest")
    other_income = ChoiceItem("Income:Other Income", "Other Income")
    paycheck = ChoiceItem("Income:Paycheck", "Paycheck")
    reimbursement = ChoiceItem("Income:Reimbursement", "Reimbursement")
    rental_income = ChoiceItem("Income:Rental Income", "Rental Income")
    education_investment = ChoiceItem(
        "Investment:Education Investment", "Education Investment"
    )
    other_investments = ChoiceItem(
        "Investment:Other Investments", "Other Investments"
    )
    retirement = ChoiceItem("Investment:Retirement", "Retirement")
    stocks_mutual_funds = ChoiceItem(
        "Investment:Stocks & Mutual Funds", "Stocks & Mutual Funds"
    )
    legal_fees = ChoiceItem("Legal:Legal Fees", "Legal Fees")
    legal_services = ChoiceItem("Legal:Legal Services", "Legal Services")
    other_legal_costs = ChoiceItem(
        "Legal:Other Legal Costs", "Other Legal Costs"
    )
    equipment = ChoiceItem("Office:Equipment", "Equipment")
    office_supplies = ChoiceItem("Office:Office Supplies", "Office Supplies")
    other_office = ChoiceItem("Office:Other Office", "Other Office")
    postage_shipping = ChoiceItem(
        "Office:Postage & Shipping", "Postage & Shipping"
    )
    accessories = ChoiceItem("Personal:Accessories", "Accessories")
    beauty = ChoiceItem("Personal:Beauty", "Beauty")
    body_enhancement = ChoiceItem(
        "Personal:Body Enhancement", "Body Enhancement"
    )
    clothing = ChoiceItem("Personal:Clothing", "Clothing")
    counseling = ChoiceItem("Personal:Counseling", "Counseling")
    hair = ChoiceItem("Personal:Hair", "Hair")
    hobbies = ChoiceItem("Personal:Hobbies", "Hobbies")
    jewelry = ChoiceItem("Personal:Jewelry", "Jewelry")
    laundry = ChoiceItem("Personal:Laundry", "Laundry")
    other_personal = ChoiceItem("Personal:Other Personal", "Other Personal")
    religion = ChoiceItem("Personal:Religion", "Religion")
    shoes = ChoiceItem("Personal:Shoes", "Shoes")
    pet_food = ChoiceItem("Pets:Pet Food", "Pet Food")
    pet_grooming = ChoiceItem("Pets:Pet Grooming", "Pet Grooming")
    pet_medicine = ChoiceItem("Pets:Pet Medicine", "Pet Medicine")
    pet_supplies = ChoiceItem("Pets:Pet Supplies", "Pet Supplies")
    veterinarian = ChoiceItem("Pets:Veterinarian", "Veterinarian")
    camping = ChoiceItem("Sports & Fitness:Camping", "Camping")
    fitness_gear = ChoiceItem("Sports & Fitness:Fitness Gear", "Fitness Gear")
    golf = ChoiceItem("Sports & Fitness:Golf", "Golf")
    memberships = ChoiceItem("Sports & Fitness:Memberships", "Memberships")
    other_sports_fitness = ChoiceItem(
        "Sports & Fitness:Other Sports & Fitness", "Other Sports & Fitness"
    )
    sporting_events = ChoiceItem(
        "Sports & Fitness:Sporting Events", "Sporting Events"
    )
    sporting_goods = ChoiceItem(
        "Sports & Fitness:Sporting Goods", "Sporting Goods"
    )
    domains_hosting = ChoiceItem(
        "Technology:Domains & Hosting", "Domains & Hosting"
    )
    hardware = ChoiceItem("Technology:Hardware", "Hardware")
    online_services = ChoiceItem(
        "Technology:Online Services", "Online Services"
    )
    software = ChoiceItem("Technology:Software", "Software")
    auto_insurance = ChoiceItem(
        "Transportation:Auto Insurance", "Auto Insurance"
    )
    auto_payment = ChoiceItem("Transportation:Auto Payment", "Auto Payment")
    auto_services = ChoiceItem("Transportation:Auto Services", "Auto Services")
    auto_supplies = ChoiceItem("Transportation:Auto Supplies", "Auto Supplies")
    bicycle = ChoiceItem("Transportation:Bicycle", "Bicycle")
    boats_marine = ChoiceItem("Transportation:Boats & Marine", "Boats & Marine")
    gas = ChoiceItem("Transportation:Gas", "Gas")
    other_transportation = ChoiceItem(
        "Transportation:Other Transportation", "Other Transportation"
    )
    parking_tolls = ChoiceItem(
        "Transportation:Parking & Tolls", "Parking & Tolls"
    )
    parking_tickets = ChoiceItem(
        "Transportation:Parking Tickets", "Parking Tickets"
    )
    public_transit = ChoiceItem(
        "Transportation:Public Transit", "Public Transit"
    )
    shipping = ChoiceItem("Transportation:Shipping", "Shipping")
    taxies = ChoiceItem("Transportation:Taxies", "Taxies")
    car_rental = ChoiceItem("Travel:Car Rental", "Car Rental")
    flights = ChoiceItem("Travel:Flights", "Flights")
    hotels = ChoiceItem("Travel:Hotels", "Hotels")
    tours_cruises = ChoiceItem("Travel:Tours & Cruises", "Tours & Cruises")
    train = ChoiceItem("Travel:Train", "Train")
    travel_buses = ChoiceItem("Travel:Travel Buses", "Travel Buses")
    travel_dining = ChoiceItem("Travel:Travel Dining", "Travel Dining")
    travel_entertainment = ChoiceItem(
        "Travel:Travel Entertainment", "Travel Entertainment"
    )
    cash = ChoiceItem("Uncategorized:Cash", "Cash")
    other_shopping = ChoiceItem(
        "Uncategorized:Other Shopping", "Other Shopping"
    )
    unknown = ChoiceItem("Uncategorized:Unknown", "Unknown")
    unassigned = ChoiceItem("Uncategorized:Unassigned", "-------")
    cable = ChoiceItem("Utilities:Cable", "Cable")
    electricity = ChoiceItem("Utilities:Electricity", "Electricity")
    gas_fuel = ChoiceItem("Utilities:Gas & Fuel", "Gas & Fuel")
    internet = ChoiceItem("Utilities:Internet", "Internet")
    other_utilities = ChoiceItem("Utilities:Other Utilities", "Other Utilities")
    phone = ChoiceItem("Utilities:Phone", "Phone")
    trash = ChoiceItem("Utilities:Trash", "Trash")
    water_sewer = ChoiceItem("Utilities:Water & Sewer", "Water & Sewer")


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
        recurring = ChoiceItem("R", "Recurring")
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    bank_account = models.ForeignKey(
        BankAccount, on_delete=models.CASCADE, editable=False
    )
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
    funding_type = models.CharField(
        max_length=1,
        choices=FundingType.choices,
        default=FundingType.target_date,
    )

    # Only relevant if the FundingType is 'target_date'
    #
    target_date = models.DateTimeField(null=True, blank=True)

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
    fillup_goal = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

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
    auto_spend = MultiSelectField(choices=TransactionCategory.choices)


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
        BankAccount, on_delete=models.CASCADE, editable=False
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
    pending = models.BooleanField(default=False, editable=False)
    memo = models.TextField(max_length=512, null=True, blank=True)
    raw_description = models.TextField(max_length=512, editable=False)
    # TODO: Initial value of the description is a cleaned up version of the
    # raw_description. It is added in post processing at the same time that
    # `party` is derived. Initially it is set to the same value as
    # 'raw_description'
    #
    # NOTE: this is filled in via the pre_save signal in ./signals.py
    #
    description = models.TextField(max_length=512)
    budget = models.ForeignKey(
        Budget,
        models.SET_NULL,
        blank=True,
        null=True,
        related_name="transactions",
    )
    account_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Posted Balance does not include pending debits.",
        editable=False,
    )
    account_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Available Balance has pending debits deducted.",
        editable=False,
    )
    budget_posted_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Posted Balance does not include pending debits.",
        editable=False,
    )
    budget_available_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        help_text="Available Balance has pending debits deducted.",
        editable=False,
    )
    # XXX Probably should make category its own object class and
    #     pre-create a bunch of those in the initial migration.
    #
    category = models.CharField(
        max_length=64,
        choices=TransactionCategory.choices,
        default=TransactionCategory.unassigned,
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
    An internal transaction moving money between budgets
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
        on_delete=models.CASCADE,
        editable=False,
        related_name="budget_debits",
    )
    dest_budget = models.ForeignKey(
        Budget,
        on_delete=models.CASCADE,
        editable=False,
        related_name="budget_credits",
    )
    actor = models.ForeignKey(User, on_delete=models.CASCADE, editable=False)
    src_budget_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        editable=False,
    )
    dst_budget_balance = MoneyField(
        max_digits=MAX_DIGITS,
        decimal_places=DECIMAL_PLACES,
        default=0,
        default_currency=settings.DEFAULT_CURRENCY,
        editable=False,
    )

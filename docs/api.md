# mibudge API

REST API for the mibudge personal budgeting service.

## Authentication

All endpoints require JWT authentication via `Authorization: Bearer <token>` header. Obtain tokens through the login flow; refresh via `POST /api/token/refresh/` (httpOnly cookie).

## Permissions

- **Banks**: read-only, any authenticated user.
- **Users**: list/retrieve/update restricted to staff; `/api/v1/users/me/` available to all authenticated users.
- **All other resources** (bank accounts, budgets, transactions, allocations, internal transactions): scoped to bank account ownership. Only users in an account's `owners` M2M can access that account and its related objects. Staff and superuser status does not bypass ownership checks.

## Money fields

Monetary values are represented as a decimal amount paired with an ISO 4217 currency code (e.g. `amount` + `amount_currency`). Currency defaults to the account's currency if not specified.

**Version:** 1.0.0

## Authentication

- **jwtAuth**: `http` (in: ``, name: ``)

## Endpoints

### api

#### `POST /api/token/`

**Operation:** `api_token_create`

JWT obtain endpoint that stores the refresh token in an httpOnly
cookie and returns only the access token in the response body.

This is the browser-SPA login flow: JS receives the short-lived
access token (kept in memory); the refresh token is a
Secure/HttpOnly/SameSite=Strict cookie that JS cannot read,
and that the browser sends automatically to /api/token/refresh/.

**Request Body** (`application/json`):

- **`username`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`username`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`username`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

**Response 200:** 

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required, read-only)*

#### `POST /api/token/refresh/`

**Operation:** `api_token_refresh_create`

JWT refresh endpoint that reads the refresh token from the httpOnly
cookie rather than the request body.

On success, returns {"access": "<new_access_token>"} in JSON.
When token rotation is enabled, also rotates the refresh cookie so
the 14-day sliding window resets with each use.

**Request Body** (`application/json`):

- **`refresh`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`refresh`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`refresh`** (`string`) *(required)*

**Response 200:** 

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required)*

### allocations

#### `GET /api/v1/allocations/`

**Operation:** `allocations_list`

Return allocations belonging to the authenticated user's transactions. Filterable by transaction, budget, and category. Orderable by created_at.

**Parameters:**

- `bank_account` (query, optional)
- `budget` (query, optional)
- `category` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `transaction` (query, optional)

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/allocations/{id}/`

**Operation:** `allocations_retrieve`

Return a single transaction allocation by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`transaction`** (`string`) *(required)*
- **`budget`** (`string`)
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`budget_balance`** (`string`) *(required, read-only)*
- **`budget_balance_currency`** (`string`) *(required, read-only)*
- **`category`** (`string`) — * `Business:Business Clothing` - Business Clothing
* `Business:Business Services` - Business Services
* `Business:Business Supplies` - Business Supplies
* `Business:Meals` - Meals
* `Business:Travel` - Travel
* `Children:Activities` - Activities
* `Children:Allowance` - Allowance
* `Children:Baby Supplies` - Baby Supplies
* `Children:Childcare` - Childcare
* `Children:Kids Clothing` - Kids Clothing
* `Children:Kids Education` - Kids Education
* `Children:Toys` - Toys
* `Culture:Art` - Art
* `Culture:Books` - Books
* `Culture:Dance` - Dance
* `Culture:Games` - Games
* `Culture:Movies` - Movies
* `Culture:Music` - Music
* `Culture:News` - News
* `Culture:Random Fun` - Random Fun
* `Culture:TV` - TV
* `Education:Books & Supplies` - Books & Supplies
* `Education:Room & Board` - Room & Board
* `Education:Student Loans` - Student Loans
* `Education: Tuition & Fees` -  Tuition & Fees
* `Fees:ATM Fees` - ATM Fees
* `Fees:Investment Fees` - Investment Fees
* `Fees:Other Fees` - Other Fees
* `Financial:Accounting` - Accounting
* `Financial:Credit Card Payment` - Credit Card Payment
* `Financial:Financial Advice` - Financial Advice
* `Financial:Life Insurance` - Life Insurance
* `Financial:Loan` - Loan
* `Financial:Loan Payment` - Loan Payment
* `Financial:Money Transfers` - Money Transfers
* `Financial:Other Financial` - Other Financial
* `Financial:Tax Preparation` - Tax Preparation
* `Financial:Taxes, Federal` - Taxes, Federal
* `Financial:Taxes, Other` - Taxes, Other
* `Financial:Taxes, State` - Taxes, State
* `Food & Drink:Alcohol & Bars` - Alcohol & Bars
* `Food & Drink:Coffee & Tea` - Coffee & Tea
* `Food & Drink:Dessert` - Dessert
* `Food & Drink:Fast Food` - Fast Food
* `Food & Drink:Groceries` - Groceries
* `Food & Drink:Other Food & Drink` - Other Food & Drink
* `Food & Drink:Restaurants` - Restaurants
* `Food & Drink:Snacks` - Snacks
* `Food & Drink:Tobacco & Like` - Tobacco & Like
* `Gifts & Donations:Charities` - Charities
* `Gifts & Donations:Gifts` - Gifts
* `Health & Medical:Care Facilities` - Care Facilities
* `Health & Medical:Dentist` - Dentist
* `Health & Medical:Doctor` - Doctor
* `Health & Medical:Equipment` - Equipment
* `Health & Medical:Eyes` - Eyes
* `Health & Medical:Health Insurance` - Health Insurance
* `Health & Medical:Other Health & Medical` - Other Health & Medical
* `Health & Medical:Pharmacies` - Pharmacies
* `Health & Medical:Prescriptions` - Prescriptions
* `Home:Furnishings` - Furnishings
* `Home:Home Insurance` - Home Insurance
* `Home:Home Purchase` - Home Purchase
* `Home:Home Services` - Home Services
* `Home:Home Supplies` - Home Supplies
* `Home:Lawn & Garden` - Lawn & Garden
* `Home:Mortgage` - Mortgage
* `Home:Moving` - Moving
* `Home:Other Home` - Other Home
* `Home:Property Tax` - Property Tax
* `Home:Rent` - Rent
* `Home:Renter's Insurance` - Renter's Insurance
* `Income:Bonus` - Bonus
* `Income:Commission` - Commission
* `Income:Interest` - Interest
* `Income:Other Income` - Other Income
* `Income:Paycheck` - Paycheck
* `Income:Reimbursement` - Reimbursement
* `Income:Rental Income` - Rental Income
* `Investment:Education Investment` - Education Investment
* `Investment:Other Investments` - Other Investments
* `Investment:Retirement` - Retirement
* `Investment:Stocks & Mutual Funds` - Stocks & Mutual Funds
* `Legal:Legal Fees` - Legal Fees
* `Legal:Legal Services` - Legal Services
* `Legal:Other Legal Costs` - Other Legal Costs
* `Office:Equipment` - Equipment
* `Office:Office Supplies` - Office Supplies
* `Office:Other Office` - Other Office
* `Office:Postage & Shipping` - Postage & Shipping
* `Personal:Accessories` - Accessories
* `Personal:Beauty` - Beauty
* `Personal:Body Enhancement` - Body Enhancement
* `Personal:Clothing` - Clothing
* `Personal:Counseling` - Counseling
* `Personal:Hair` - Hair
* `Personal:Hobbies` - Hobbies
* `Personal:Jewelry` - Jewelry
* `Personal:Laundry` - Laundry
* `Personal:Other Personal` - Other Personal
* `Personal:Religion` - Religion
* `Personal:Shoes` - Shoes
* `Pets:Pet Food` - Pet Food
* `Pets:Pet Grooming` - Pet Grooming
* `Pets:Pet Medicine` - Pet Medicine
* `Pets:Pet Supplies` - Pet Supplies
* `Pets:Veterinarian` - Veterinarian
* `Sports & Fitness:Camping` - Camping
* `Sports & Fitness:Fitness Gear` - Fitness Gear
* `Sports & Fitness:Golf` - Golf
* `Sports & Fitness:Memberships` - Memberships
* `Sports & Fitness:Other Sports & Fitness` - Other Sports & Fitness
* `Sports & Fitness:Sporting Events` - Sporting Events
* `Sports & Fitness:Sporting Goods` - Sporting Goods
* `Technology:Domains & Hosting` - Domains & Hosting
* `Technology:Hardware` - Hardware
* `Technology:Online Services` - Online Services
* `Technology:Software` - Software
* `Transportation:Auto Insurance` - Auto Insurance
* `Transportation:Auto Payment` - Auto Payment
* `Transportation:Auto Services` - Auto Services
* `Transportation:Auto Supplies` - Auto Supplies
* `Transportation:Bicycle` - Bicycle
* `Transportation:Boats & Marine` - Boats & Marine
* `Transportation:Gas` - Gas
* `Transportation:Other Transportation` - Other Transportation
* `Transportation:Parking & Tolls` - Parking & Tolls
* `Transportation:Parking Tickets` - Parking Tickets
* `Transportation:Public Transit` - Public Transit
* `Transportation:Shipping` - Shipping
* `Transportation:Taxies` - Taxies
* `Travel:Car Rental` - Car Rental
* `Travel:Flights` - Flights
* `Travel:Hotels` - Hotels
* `Travel:Tours & Cruises` - Tours & Cruises
* `Travel:Train` - Train
* `Travel:Travel Buses` - Travel Buses
* `Travel:Travel Dining` - Travel Dining
* `Travel:Travel Entertainment` - Travel Entertainment
* `Uncategorized:Cash` - Cash
* `Uncategorized:Other Shopping` - Other Shopping
* `Uncategorized:Unknown` - Unknown
* `Uncategorized:Unassigned` - -------
* `Utilities:Cable` - Cable
* `Utilities:Electricity` - Electricity
* `Utilities:Gas & Fuel` - Gas & Fuel
* `Utilities:Internet` - Internet
* `Utilities:Other Utilities` - Other Utilities
* `Utilities:Phone` - Phone
* `Utilities:Trash` - Trash
* `Utilities:Water & Sewer` - Water & Sewer Enum: ['Business:Business Clothing', 'Business:Business Services', 'Business:Business Supplies', 'Business:Meals', 'Business:Travel', 'Children:Activities', 'Children:Allowance', 'Children:Baby Supplies', 'Children:Childcare', 'Children:Kids Clothing', 'Children:Kids Education', 'Children:Toys', 'Culture:Art', 'Culture:Books', 'Culture:Dance', 'Culture:Games', 'Culture:Movies', 'Culture:Music', 'Culture:News', 'Culture:Random Fun', 'Culture:TV', 'Education:Books & Supplies', 'Education:Room & Board', 'Education:Student Loans', 'Education: Tuition & Fees', 'Fees:ATM Fees', 'Fees:Investment Fees', 'Fees:Other Fees', 'Financial:Accounting', 'Financial:Credit Card Payment', 'Financial:Financial Advice', 'Financial:Life Insurance', 'Financial:Loan', 'Financial:Loan Payment', 'Financial:Money Transfers', 'Financial:Other Financial', 'Financial:Tax Preparation', 'Financial:Taxes, Federal', 'Financial:Taxes, Other', 'Financial:Taxes, State', 'Food & Drink:Alcohol & Bars', 'Food & Drink:Coffee & Tea', 'Food & Drink:Dessert', 'Food & Drink:Fast Food', 'Food & Drink:Groceries', 'Food & Drink:Other Food & Drink', 'Food & Drink:Restaurants', 'Food & Drink:Snacks', 'Food & Drink:Tobacco & Like', 'Gifts & Donations:Charities', 'Gifts & Donations:Gifts', 'Health & Medical:Care Facilities', 'Health & Medical:Dentist', 'Health & Medical:Doctor', 'Health & Medical:Equipment', 'Health & Medical:Eyes', 'Health & Medical:Health Insurance', 'Health & Medical:Other Health & Medical', 'Health & Medical:Pharmacies', 'Health & Medical:Prescriptions', 'Home:Furnishings', 'Home:Home Insurance', 'Home:Home Purchase', 'Home:Home Services', 'Home:Home Supplies', 'Home:Lawn & Garden', 'Home:Mortgage', 'Home:Moving', 'Home:Other Home', 'Home:Property Tax', 'Home:Rent', "Home:Renter's Insurance", 'Income:Bonus', 'Income:Commission', 'Income:Interest', 'Income:Other Income', 'Income:Paycheck', 'Income:Reimbursement', 'Income:Rental Income', 'Investment:Education Investment', 'Investment:Other Investments', 'Investment:Retirement', 'Investment:Stocks & Mutual Funds', 'Legal:Legal Fees', 'Legal:Legal Services', 'Legal:Other Legal Costs', 'Office:Equipment', 'Office:Office Supplies', 'Office:Other Office', 'Office:Postage & Shipping', 'Personal:Accessories', 'Personal:Beauty', 'Personal:Body Enhancement', 'Personal:Clothing', 'Personal:Counseling', 'Personal:Hair', 'Personal:Hobbies', 'Personal:Jewelry', 'Personal:Laundry', 'Personal:Other Personal', 'Personal:Religion', 'Personal:Shoes', 'Pets:Pet Food', 'Pets:Pet Grooming', 'Pets:Pet Medicine', 'Pets:Pet Supplies', 'Pets:Veterinarian', 'Sports & Fitness:Camping', 'Sports & Fitness:Fitness Gear', 'Sports & Fitness:Golf', 'Sports & Fitness:Memberships', 'Sports & Fitness:Other Sports & Fitness', 'Sports & Fitness:Sporting Events', 'Sports & Fitness:Sporting Goods', 'Technology:Domains & Hosting', 'Technology:Hardware', 'Technology:Online Services', 'Technology:Software', 'Transportation:Auto Insurance', 'Transportation:Auto Payment', 'Transportation:Auto Services', 'Transportation:Auto Supplies', 'Transportation:Bicycle', 'Transportation:Boats & Marine', 'Transportation:Gas', 'Transportation:Other Transportation', 'Transportation:Parking & Tolls', 'Transportation:Parking Tickets', 'Transportation:Public Transit', 'Transportation:Shipping', 'Transportation:Taxies', 'Travel:Car Rental', 'Travel:Flights', 'Travel:Hotels', 'Travel:Tours & Cruises', 'Travel:Train', 'Travel:Travel Buses', 'Travel:Travel Dining', 'Travel:Travel Entertainment', 'Uncategorized:Cash', 'Uncategorized:Other Shopping', 'Uncategorized:Unknown', 'Uncategorized:Unassigned', 'Utilities:Cable', 'Utilities:Electricity', 'Utilities:Gas & Fuel', 'Utilities:Internet', 'Utilities:Other Utilities', 'Utilities:Phone', 'Utilities:Trash', 'Utilities:Water & Sewer']
- **`memo`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### bank-accounts

#### `GET /api/v1/bank-accounts/`

**Operation:** `bank_accounts_list`

Return bank accounts owned by the authenticated user. Filterable by account_type. Orderable by name or created_at.

**Parameters:**

- `account_type` (query, optional) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/bank-accounts/`

**Operation:** `bank_accounts_create`

Create a new bank account. The authenticated user is automatically added as an owner. An 'Unallocated' budget is auto-created by a post_save signal. Optionally set initial posted_balance, available_balance, and currency (all immutable after creation).

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_retrieve`

Return a single bank account by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_update`

Full update of a bank account. Only 'name' is mutable after creation -- bank, account_type, currency, and balances are rejected if changed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_partial_update`

Partial update of a bank account. Only 'name' is mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/bank-accounts/{id}/`

**Operation:** `bank_accounts_destroy`

Delete a bank account and all associated budgets, transactions, and allocations.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

### banks

#### `GET /api/v1/banks/`

**Operation:** `banks_list`

Return all banks in the system. Banks are shared reference data managed through the admin -- any authenticated user can list and retrieve them.

**Parameters:**

- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/banks/{id}/`

**Operation:** `banks_retrieve`

Return a single bank by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)*
- **`routing_number`** (`string`) *(required, read-only)*
- **`default_currency`** (`string`) *(required, read-only)* — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### budgets

#### `GET /api/v1/budgets/`

**Operation:** `budgets_list`

Return budgets belonging to the authenticated user's accounts. Filterable by bank_account, budget_type, archived, and paused. Searchable by name. Orderable by name, created_at, or balance.

**Parameters:**

- `archived` (query, optional)
- `bank_account` (query, optional)
- `budget_type` (query, optional) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `paused` (query, optional)
- `search` (query, optional) — A search term.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/budgets/`

**Operation:** `budgets_create`

Create a new budget under a bank account. Required: name, bank_account (UUID), budget_type, funding_type, and target_balance. The bank_account and budget_type are immutable after creation. Balance is managed by signals and is always read-only.

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/budgets/{id}/`

**Operation:** `budgets_retrieve`

Return a single budget by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/budgets/{id}/`

**Operation:** `budgets_update`

Full update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/budgets/{id}/`

**Operation:** `budgets_partial_update`

Partial update of a budget. bank_account and budget_type are immutable. The unallocated budget cannot be renamed.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/budgets/{id}/`

**Operation:** `budgets_destroy`

Delete a budget. The unallocated budget cannot be deleted (403). A budget with existing transaction allocations cannot be deleted (400) -- archive it instead.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

#### `POST /api/v1/budgets/{id}/archive/`

**Operation:** `budgets_archive_create`

Archive a budget. Any remaining balance is transferred to the account's unallocated budget. If the budget has an associated fill-up goal, that budget is also archived and its balance moved to unallocated. The unallocated budget cannot be archived.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`application/x-www-form-urlencoded`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Request Body** (`multipart/form-data`):

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### currencies

#### `GET /api/v1/currencies/`

**Operation:** `currencies_retrieve`

Return all ISO 4217 currency codes supported by the system, sorted by code. Each entry includes the code, English name, and numeric ISO 4217 code. Requires authentication.

**Response 200:** List of supported currencies.

### internal-transactions

#### `GET /api/v1/internal-transactions/`

**Operation:** `internal_transactions_list`

Return budget-to-budget transfers belonging to the authenticated user's accounts. Filterable by bank_account, src_budget, dst_budget, and date range (date_from/date_to). Orderable by created_at.

**Parameters:**

- `bank_account` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `dst_budget` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `src_budget` (query, optional)

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/internal-transactions/`

**Operation:** `internal_transactions_create`

Transfer money between two budgets in the same bank account. Required: bank_account (UUID), amount, src_budget (UUID), and dst_budget (UUID). The authenticated user is recorded as the actor. Internal transactions are write-once -- to reverse a transfer, create a new one with src and dst swapped.

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/internal-transactions/{id}/`

**Operation:** `internal_transactions_retrieve`

Return a single internal transaction by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### transactions

#### `GET /api/v1/transactions/`

**Operation:** `transactions_list`

Return transactions belonging to the authenticated user's accounts. Filterable by bank_account, pending status, transaction_type, and date range (date_from/date_to). Searchable by description, raw_description, and party. Orderable by transaction_date, amount, or created_at.

**Parameters:**

- `bank_account` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `pending` (query, optional)
- `search` (query, optional) — A search term.
- `transaction_type` (query, optional) — * `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `POST /api/v1/transactions/`

**Operation:** `transactions_create`

Create a new bank transaction. Required: bank_account (UUID), amount, transaction_date, transaction_type, and raw_description. A default TransactionAllocation to the bank account's unallocated budget is auto-created. After creation, only transaction_type, memo, and description are updatable.

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 201:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `GET /api/v1/transactions/{id}/`

**Operation:** `transactions_retrieve`

Return a single transaction by UUID.

**Parameters:**

- `id` (path, required)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PUT /api/v1/transactions/{id}/`

**Operation:** `transactions_update`

Full update of a transaction. Only transaction_type, memo, and description are mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/transactions/{id}/`

**Operation:** `transactions_partial_update`

Partial update of a transaction. Only transaction_type, memo, and description are mutable after creation.

**Parameters:**

- `id` (path, required)

**Request Body** (`application/json`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Request Body** (`multipart/form-data`):

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

**Response 200:** 

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

#### `DELETE /api/v1/transactions/{id}/`

**Operation:** `transactions_destroy`

Delete a transaction. Balance changes are reversed by the pre_delete signal. Associated allocations are cascade-deleted.

**Parameters:**

- `id` (path, required)

**Response 204:** No response body

#### `POST /api/v1/transactions/{id}/splits/`

**Operation:** `transactions_splits_create`

Declaratively set how a transaction's amount is split across budgets. All referenced budgets must belong to the same bank account as the transaction. The backend reconciles existing allocations to match: creating, updating, or deleting as needed. Any unallocated remainder gets an allocation to the account's unallocated budget. Returns all allocations for this transaction after reconciliation.

**Parameters:**

- `bank_account` (query, optional)
- `date_from` (query, optional)
- `date_to` (query, optional)
- `id` (path, required)
- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.
- `pending` (query, optional)
- `search` (query, optional) — A search term.
- `transaction_type` (query, optional) — * `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------

**Request Body** (`application/json`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Request Body** (`application/x-www-form-urlencoded`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Request Body** (`multipart/form-data`):

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### users

#### `GET /api/v1/users/`

**Operation:** `users_list`

Return all users. Restricted to staff/admin users.

**Parameters:**

- `ordering` (query, optional) — Which field to use when ordering the results.
- `page` (query, optional) — A page number within the paginated result set.
- `page_size` (query, optional) — Number of results to return per page.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/v1/users/{username}/`

**Operation:** `users_retrieve`

Return a single user by username. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

#### `PUT /api/v1/users/{username}/`

**Operation:** `users_update`

Full update of a user profile. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Request Body** (`application/json`):

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Request Body** (`multipart/form-data`):

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

#### `PATCH /api/v1/users/{username}/`

**Operation:** `users_partial_update`

Partial update of a user profile. Restricted to staff/admin users.

**Parameters:**

- `username` (path, required)

**Request Body** (`application/json`):

- **`username`** (`string`) — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Request Body** (`application/x-www-form-urlencoded`):

- **`username`** (`string`) — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Request Body** (`multipart/form-data`):

- **`username`** (`string`) — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

#### `GET /api/v1/users/me/`

**Operation:** `users_me_retrieve`

Return the authenticated user's own profile. Available to any authenticated user (not restricted to staff).

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

## Schemas

### AccountTypeEnum

* `C` - Checking
* `S` - Savings
* `X` - Credit Card


### Bank

Read-only serializer for banks.

Banks are shared reference data managed only through the admin.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required, read-only)*
- **`routing_number`** (`string`) *(required, read-only)*
- **`default_currency`** (`string`) *(required, read-only)* — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BankAccount

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
and optionally currency, account_number, and initial balances.
The view adds the requesting user to owners.  The unallocated
budget is auto-created by the post_save signal and returned in
the response.

After creation only name is updatable.  Currency, account_number,
and balances are immutable once the account exists.

Group assignment is not yet supported via the API.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`owners`** (`array`) *(required, read-only)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`posted_balance_currency`** (`string`) *(required, read-only)*
- **`available_balance`** (`string`)
- **`available_balance_currency`** (`string`) *(required, read-only)*
- **`unallocated_budget`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BankAccountRequest

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
and optionally currency, account_number, and initial balances.
The view adds the requesting user to owners.  The unallocated
budget is auto-created by the post_save signal and returned in
the response.

After creation only name is updatable.  Currency, account_number,
and balances are immutable once the account exists.

Group assignment is not yet supported via the API.

- **`name`** (`string`) *(required)*
- **`bank`** (`string`) *(required)*
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

### BlankEnum


### Budget

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`id`** (`string`) *(required, read-only)*
- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`balance`** (`string`) *(required, read-only)*
- **`balance_currency`** (`string`) *(required, read-only)*
- **`target_balance`** (`string`) *(required)*
- **`target_balance_currency`** (`string`) *(required, read-only)*
- **`funding_amount`** (`string`)
- **`funding_amount_currency`** (`string`) *(required, read-only)*
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`archived`** (`boolean`) *(required, read-only)*
- **`archived_at`** (`string`) *(required, read-only)*
- **`complete`** (`boolean`) *(required, read-only)* — True when this budget has reached its target and should not be funded further.  Managed by signals and funding tasks; do not set manually.
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### BudgetRequest

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`name`** (`string`) *(required)*
- **`bank_account`** (`string`) *(required)*
- **`target_balance`** (`string`) *(required)*
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

### BudgetTypeEnum

* `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped


### CategoryEnum

* `Business:Business Clothing` - Business Clothing
* `Business:Business Services` - Business Services
* `Business:Business Supplies` - Business Supplies
* `Business:Meals` - Meals
* `Business:Travel` - Travel
* `Children:Activities` - Activities
* `Children:Allowance` - Allowance
* `Children:Baby Supplies` - Baby Supplies
* `Children:Childcare` - Childcare
* `Children:Kids Clothing` - Kids Clothing
* `Children:Kids Education` - Kids Education
* `Children:Toys` - Toys
* `Culture:Art` - Art
* `Culture:Books` - Books
* `Culture:Dance` - Dance
* `Culture:Games` - Games
* `Culture:Movies` - Movies
* `Culture:Music` - Music
* `Culture:News` - News
* `Culture:Random Fun` - Random Fun
* `Culture:TV` - TV
* `Education:Books & Supplies` - Books & Supplies
* `Education:Room & Board` - Room & Board
* `Education:Student Loans` - Student Loans
* `Education: Tuition & Fees` -  Tuition & Fees
* `Fees:ATM Fees` - ATM Fees
* `Fees:Investment Fees` - Investment Fees
* `Fees:Other Fees` - Other Fees
* `Financial:Accounting` - Accounting
* `Financial:Credit Card Payment` - Credit Card Payment
* `Financial:Financial Advice` - Financial Advice
* `Financial:Life Insurance` - Life Insurance
* `Financial:Loan` - Loan
* `Financial:Loan Payment` - Loan Payment
* `Financial:Money Transfers` - Money Transfers
* `Financial:Other Financial` - Other Financial
* `Financial:Tax Preparation` - Tax Preparation
* `Financial:Taxes, Federal` - Taxes, Federal
* `Financial:Taxes, Other` - Taxes, Other
* `Financial:Taxes, State` - Taxes, State
* `Food & Drink:Alcohol & Bars` - Alcohol & Bars
* `Food & Drink:Coffee & Tea` - Coffee & Tea
* `Food & Drink:Dessert` - Dessert
* `Food & Drink:Fast Food` - Fast Food
* `Food & Drink:Groceries` - Groceries
* `Food & Drink:Other Food & Drink` - Other Food & Drink
* `Food & Drink:Restaurants` - Restaurants
* `Food & Drink:Snacks` - Snacks
* `Food & Drink:Tobacco & Like` - Tobacco & Like
* `Gifts & Donations:Charities` - Charities
* `Gifts & Donations:Gifts` - Gifts
* `Health & Medical:Care Facilities` - Care Facilities
* `Health & Medical:Dentist` - Dentist
* `Health & Medical:Doctor` - Doctor
* `Health & Medical:Equipment` - Equipment
* `Health & Medical:Eyes` - Eyes
* `Health & Medical:Health Insurance` - Health Insurance
* `Health & Medical:Other Health & Medical` - Other Health & Medical
* `Health & Medical:Pharmacies` - Pharmacies
* `Health & Medical:Prescriptions` - Prescriptions
* `Home:Furnishings` - Furnishings
* `Home:Home Insurance` - Home Insurance
* `Home:Home Purchase` - Home Purchase
* `Home:Home Services` - Home Services
* `Home:Home Supplies` - Home Supplies
* `Home:Lawn & Garden` - Lawn & Garden
* `Home:Mortgage` - Mortgage
* `Home:Moving` - Moving
* `Home:Other Home` - Other Home
* `Home:Property Tax` - Property Tax
* `Home:Rent` - Rent
* `Home:Renter's Insurance` - Renter's Insurance
* `Income:Bonus` - Bonus
* `Income:Commission` - Commission
* `Income:Interest` - Interest
* `Income:Other Income` - Other Income
* `Income:Paycheck` - Paycheck
* `Income:Reimbursement` - Reimbursement
* `Income:Rental Income` - Rental Income
* `Investment:Education Investment` - Education Investment
* `Investment:Other Investments` - Other Investments
* `Investment:Retirement` - Retirement
* `Investment:Stocks & Mutual Funds` - Stocks & Mutual Funds
* `Legal:Legal Fees` - Legal Fees
* `Legal:Legal Services` - Legal Services
* `Legal:Other Legal Costs` - Other Legal Costs
* `Office:Equipment` - Equipment
* `Office:Office Supplies` - Office Supplies
* `Office:Other Office` - Other Office
* `Office:Postage & Shipping` - Postage & Shipping
* `Personal:Accessories` - Accessories
* `Personal:Beauty` - Beauty
* `Personal:Body Enhancement` - Body Enhancement
* `Personal:Clothing` - Clothing
* `Personal:Counseling` - Counseling
* `Personal:Hair` - Hair
* `Personal:Hobbies` - Hobbies
* `Personal:Jewelry` - Jewelry
* `Personal:Laundry` - Laundry
* `Personal:Other Personal` - Other Personal
* `Personal:Religion` - Religion
* `Personal:Shoes` - Shoes
* `Pets:Pet Food` - Pet Food
* `Pets:Pet Grooming` - Pet Grooming
* `Pets:Pet Medicine` - Pet Medicine
* `Pets:Pet Supplies` - Pet Supplies
* `Pets:Veterinarian` - Veterinarian
* `Sports & Fitness:Camping` - Camping
* `Sports & Fitness:Fitness Gear` - Fitness Gear
* `Sports & Fitness:Golf` - Golf
* `Sports & Fitness:Memberships` - Memberships
* `Sports & Fitness:Other Sports & Fitness` - Other Sports & Fitness
* `Sports & Fitness:Sporting Events` - Sporting Events
* `Sports & Fitness:Sporting Goods` - Sporting Goods
* `Technology:Domains & Hosting` - Domains & Hosting
* `Technology:Hardware` - Hardware
* `Technology:Online Services` - Online Services
* `Technology:Software` - Software
* `Transportation:Auto Insurance` - Auto Insurance
* `Transportation:Auto Payment` - Auto Payment
* `Transportation:Auto Services` - Auto Services
* `Transportation:Auto Supplies` - Auto Supplies
* `Transportation:Bicycle` - Bicycle
* `Transportation:Boats & Marine` - Boats & Marine
* `Transportation:Gas` - Gas
* `Transportation:Other Transportation` - Other Transportation
* `Transportation:Parking & Tolls` - Parking & Tolls
* `Transportation:Parking Tickets` - Parking Tickets
* `Transportation:Public Transit` - Public Transit
* `Transportation:Shipping` - Shipping
* `Transportation:Taxies` - Taxies
* `Travel:Car Rental` - Car Rental
* `Travel:Flights` - Flights
* `Travel:Hotels` - Hotels
* `Travel:Tours & Cruises` - Tours & Cruises
* `Travel:Train` - Train
* `Travel:Travel Buses` - Travel Buses
* `Travel:Travel Dining` - Travel Dining
* `Travel:Travel Entertainment` - Travel Entertainment
* `Uncategorized:Cash` - Cash
* `Uncategorized:Other Shopping` - Other Shopping
* `Uncategorized:Unknown` - Unknown
* `Uncategorized:Unassigned` - -------
* `Utilities:Cable` - Cable
* `Utilities:Electricity` - Electricity
* `Utilities:Gas & Fuel` - Gas & Fuel
* `Utilities:Internet` - Internet
* `Utilities:Other Utilities` - Other Utilities
* `Utilities:Phone` - Phone
* `Utilities:Trash` - Trash
* `Utilities:Water & Sewer` - Water & Sewer


### FundingTypeEnum

* `D` - Target Date
* `F` - Fixed Amount


### InternalTransaction

Serializer for internal transactions (budget-to-budget transfers).

Internal transactions are write-once: the API supports create and
read but not update or delete.  To reverse a transfer, create a
new internal transaction with the src and dst budgets swapped.

On create the caller supplies bank_account, amount, src_budget,
and dst_budget.  The view sets the actor to the requesting user.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*
- **`actor`** (`integer`) *(required, read-only)*
- **`src_budget_balance`** (`string`) *(required, read-only)*
- **`src_budget_balance_currency`** (`string`) *(required, read-only)*
- **`dst_budget_balance`** (`string`) *(required, read-only)*
- **`dst_budget_balance_currency`** (`string`) *(required, read-only)*
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### InternalTransactionRequest

Serializer for internal transactions (budget-to-budget transfers).

Internal transactions are write-once: the API supports create and
read but not update or delete.  To reverse a transfer, create a
new internal transaction with the src and dst budgets swapped.

On create the caller supplies bank_account, amount, src_budget,
and dst_budget.  The view sets the actor to the requesting user.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`src_budget`** (`string`) *(required)*
- **`dst_budget`** (`string`) *(required)*

### PaginatedBankAccountList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBankList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedBudgetList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedInternalTransactionList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedTransactionAllocationList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedTransactionList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PaginatedUserList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PatchedBankAccountRequest

Serializer for bank accounts.

On create the caller supplies name, bank (UUID), account_type,
and optionally currency, account_number, and initial balances.
The view adds the requesting user to owners.  The unallocated
budget is auto-created by the post_save signal and returned in
the response.

After creation only name is updatable.  Currency, account_number,
and balances are immutable once the account exists.

Group assignment is not yet supported via the API.

- **`name`** (`string`)
- **`bank`** (`string`)
- **`account_type`** (`string`) — * `C` - Checking
* `S` - Savings
* `X` - Credit Card Enum: ['C', 'S', 'X']
- **`account_number`** (`string`)
- **`currency`** (`string`) — ISO 4217 currency code (e.g. USD, EUR, GBP).
- **`posted_balance`** (`string`)
- **`available_balance`** (`string`)

### PatchedBudgetRequest

Serializer for budgets.

On create the caller supplies bank_account (UUID) and budget
properties.  After creation, bank_account and budget_type are
immutable.  Balance is managed by signals and is always read-only.
The unallocated budget's name cannot be changed.

Currency is inherited from the bank account via the pre_save
signal and is not accepted from the client.

- **`name`** (`string`)
- **`bank_account`** (`string`)
- **`target_balance`** (`string`)
- **`funding_amount`** (`string`)
- **`budget_type`** (`string`) — * `G` - Goal
* `R` - Recurring
* `A` - Associated Fill-up Goal
* `C` - Capped Enum: ['G', 'R', 'A', 'C']
- **`funding_type`** (`string`) — * `D` - Target Date
* `F` - Fixed Amount Enum: ['D', 'F']
- **`target_date`** (`string`)
- **`with_fillup_goal`** (`boolean`)
- **`fillup_goal`** (`string`)
- **`paused`** (`boolean`) — A paused budget does not get automatically funded on its schedule.
- **`funding_schedule`** (`string`)
- **`recurrance_schedule`** (`string`)
- **`memo`** (`string`)
- **`auto_spend`** (``)

### PatchedTransactionRequest

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`)
- **`amount`** (`string`)
- **`transaction_date`** (`string`)
- **`transaction_type`** (``)
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`)
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

### PatchedUserRequest

- **`username`** (`string`) — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

### TokenObtainPair

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required, read-only)*

### TokenObtainPairRequest

- **`username`** (`string`) *(required)*
- **`password`** (`string`) *(required)*

### TokenRefresh

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required)*

### TokenRefreshRequest

- **`refresh`** (`string`) *(required)*

### Transaction

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`party`** (`string`) *(required, read-only)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`linked_transaction`** (`string`) *(required, read-only)*
- **`bank_account_posted_balance`** (`string`) *(required, read-only)* — Posted Balance does not include pending debits.
- **`bank_account_posted_balance_currency`** (`string`) *(required, read-only)*
- **`bank_account_available_balance`** (`string`) *(required, read-only)* — Available Balance has pending debits deducted.
- **`bank_account_available_balance_currency`** (`string`) *(required, read-only)*
- **`image`** (`string`)
- **`document`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### TransactionAllocation

Serializer for transaction allocations.

An allocation maps a portion of a transaction's amount to a budget.
On create the caller supplies transaction, amount, and optionally
budget (defaults to unallocated) and category.  After creation,
budget, category, and memo are updatable.

The serializer enforces two key constraints:

1. **Same-account restriction** -- the budget must belong to the
   same bank account as the transaction.  Cross-account allocations
   are rejected with a 400 error.
2. **Sum constraint** -- the total allocated amount across all
   allocations for a transaction must not exceed the transaction
   amount.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`id`** (`string`) *(required, read-only)*
- **`transaction`** (`string`) *(required)*
- **`budget`** (`string`)
- **`amount`** (`string`) *(required)*
- **`amount_currency`** (`string`) *(required, read-only)*
- **`budget_balance`** (`string`) *(required, read-only)*
- **`budget_balance_currency`** (`string`) *(required, read-only)*
- **`category`** (`string`) — * `Business:Business Clothing` - Business Clothing
* `Business:Business Services` - Business Services
* `Business:Business Supplies` - Business Supplies
* `Business:Meals` - Meals
* `Business:Travel` - Travel
* `Children:Activities` - Activities
* `Children:Allowance` - Allowance
* `Children:Baby Supplies` - Baby Supplies
* `Children:Childcare` - Childcare
* `Children:Kids Clothing` - Kids Clothing
* `Children:Kids Education` - Kids Education
* `Children:Toys` - Toys
* `Culture:Art` - Art
* `Culture:Books` - Books
* `Culture:Dance` - Dance
* `Culture:Games` - Games
* `Culture:Movies` - Movies
* `Culture:Music` - Music
* `Culture:News` - News
* `Culture:Random Fun` - Random Fun
* `Culture:TV` - TV
* `Education:Books & Supplies` - Books & Supplies
* `Education:Room & Board` - Room & Board
* `Education:Student Loans` - Student Loans
* `Education: Tuition & Fees` -  Tuition & Fees
* `Fees:ATM Fees` - ATM Fees
* `Fees:Investment Fees` - Investment Fees
* `Fees:Other Fees` - Other Fees
* `Financial:Accounting` - Accounting
* `Financial:Credit Card Payment` - Credit Card Payment
* `Financial:Financial Advice` - Financial Advice
* `Financial:Life Insurance` - Life Insurance
* `Financial:Loan` - Loan
* `Financial:Loan Payment` - Loan Payment
* `Financial:Money Transfers` - Money Transfers
* `Financial:Other Financial` - Other Financial
* `Financial:Tax Preparation` - Tax Preparation
* `Financial:Taxes, Federal` - Taxes, Federal
* `Financial:Taxes, Other` - Taxes, Other
* `Financial:Taxes, State` - Taxes, State
* `Food & Drink:Alcohol & Bars` - Alcohol & Bars
* `Food & Drink:Coffee & Tea` - Coffee & Tea
* `Food & Drink:Dessert` - Dessert
* `Food & Drink:Fast Food` - Fast Food
* `Food & Drink:Groceries` - Groceries
* `Food & Drink:Other Food & Drink` - Other Food & Drink
* `Food & Drink:Restaurants` - Restaurants
* `Food & Drink:Snacks` - Snacks
* `Food & Drink:Tobacco & Like` - Tobacco & Like
* `Gifts & Donations:Charities` - Charities
* `Gifts & Donations:Gifts` - Gifts
* `Health & Medical:Care Facilities` - Care Facilities
* `Health & Medical:Dentist` - Dentist
* `Health & Medical:Doctor` - Doctor
* `Health & Medical:Equipment` - Equipment
* `Health & Medical:Eyes` - Eyes
* `Health & Medical:Health Insurance` - Health Insurance
* `Health & Medical:Other Health & Medical` - Other Health & Medical
* `Health & Medical:Pharmacies` - Pharmacies
* `Health & Medical:Prescriptions` - Prescriptions
* `Home:Furnishings` - Furnishings
* `Home:Home Insurance` - Home Insurance
* `Home:Home Purchase` - Home Purchase
* `Home:Home Services` - Home Services
* `Home:Home Supplies` - Home Supplies
* `Home:Lawn & Garden` - Lawn & Garden
* `Home:Mortgage` - Mortgage
* `Home:Moving` - Moving
* `Home:Other Home` - Other Home
* `Home:Property Tax` - Property Tax
* `Home:Rent` - Rent
* `Home:Renter's Insurance` - Renter's Insurance
* `Income:Bonus` - Bonus
* `Income:Commission` - Commission
* `Income:Interest` - Interest
* `Income:Other Income` - Other Income
* `Income:Paycheck` - Paycheck
* `Income:Reimbursement` - Reimbursement
* `Income:Rental Income` - Rental Income
* `Investment:Education Investment` - Education Investment
* `Investment:Other Investments` - Other Investments
* `Investment:Retirement` - Retirement
* `Investment:Stocks & Mutual Funds` - Stocks & Mutual Funds
* `Legal:Legal Fees` - Legal Fees
* `Legal:Legal Services` - Legal Services
* `Legal:Other Legal Costs` - Other Legal Costs
* `Office:Equipment` - Equipment
* `Office:Office Supplies` - Office Supplies
* `Office:Other Office` - Other Office
* `Office:Postage & Shipping` - Postage & Shipping
* `Personal:Accessories` - Accessories
* `Personal:Beauty` - Beauty
* `Personal:Body Enhancement` - Body Enhancement
* `Personal:Clothing` - Clothing
* `Personal:Counseling` - Counseling
* `Personal:Hair` - Hair
* `Personal:Hobbies` - Hobbies
* `Personal:Jewelry` - Jewelry
* `Personal:Laundry` - Laundry
* `Personal:Other Personal` - Other Personal
* `Personal:Religion` - Religion
* `Personal:Shoes` - Shoes
* `Pets:Pet Food` - Pet Food
* `Pets:Pet Grooming` - Pet Grooming
* `Pets:Pet Medicine` - Pet Medicine
* `Pets:Pet Supplies` - Pet Supplies
* `Pets:Veterinarian` - Veterinarian
* `Sports & Fitness:Camping` - Camping
* `Sports & Fitness:Fitness Gear` - Fitness Gear
* `Sports & Fitness:Golf` - Golf
* `Sports & Fitness:Memberships` - Memberships
* `Sports & Fitness:Other Sports & Fitness` - Other Sports & Fitness
* `Sports & Fitness:Sporting Events` - Sporting Events
* `Sports & Fitness:Sporting Goods` - Sporting Goods
* `Technology:Domains & Hosting` - Domains & Hosting
* `Technology:Hardware` - Hardware
* `Technology:Online Services` - Online Services
* `Technology:Software` - Software
* `Transportation:Auto Insurance` - Auto Insurance
* `Transportation:Auto Payment` - Auto Payment
* `Transportation:Auto Services` - Auto Services
* `Transportation:Auto Supplies` - Auto Supplies
* `Transportation:Bicycle` - Bicycle
* `Transportation:Boats & Marine` - Boats & Marine
* `Transportation:Gas` - Gas
* `Transportation:Other Transportation` - Other Transportation
* `Transportation:Parking & Tolls` - Parking & Tolls
* `Transportation:Parking Tickets` - Parking Tickets
* `Transportation:Public Transit` - Public Transit
* `Transportation:Shipping` - Shipping
* `Transportation:Taxies` - Taxies
* `Travel:Car Rental` - Car Rental
* `Travel:Flights` - Flights
* `Travel:Hotels` - Hotels
* `Travel:Tours & Cruises` - Tours & Cruises
* `Travel:Train` - Train
* `Travel:Travel Buses` - Travel Buses
* `Travel:Travel Dining` - Travel Dining
* `Travel:Travel Entertainment` - Travel Entertainment
* `Uncategorized:Cash` - Cash
* `Uncategorized:Other Shopping` - Other Shopping
* `Uncategorized:Unknown` - Unknown
* `Uncategorized:Unassigned` - -------
* `Utilities:Cable` - Cable
* `Utilities:Electricity` - Electricity
* `Utilities:Gas & Fuel` - Gas & Fuel
* `Utilities:Internet` - Internet
* `Utilities:Other Utilities` - Other Utilities
* `Utilities:Phone` - Phone
* `Utilities:Trash` - Trash
* `Utilities:Water & Sewer` - Water & Sewer Enum: ['Business:Business Clothing', 'Business:Business Services', 'Business:Business Supplies', 'Business:Meals', 'Business:Travel', 'Children:Activities', 'Children:Allowance', 'Children:Baby Supplies', 'Children:Childcare', 'Children:Kids Clothing', 'Children:Kids Education', 'Children:Toys', 'Culture:Art', 'Culture:Books', 'Culture:Dance', 'Culture:Games', 'Culture:Movies', 'Culture:Music', 'Culture:News', 'Culture:Random Fun', 'Culture:TV', 'Education:Books & Supplies', 'Education:Room & Board', 'Education:Student Loans', 'Education: Tuition & Fees', 'Fees:ATM Fees', 'Fees:Investment Fees', 'Fees:Other Fees', 'Financial:Accounting', 'Financial:Credit Card Payment', 'Financial:Financial Advice', 'Financial:Life Insurance', 'Financial:Loan', 'Financial:Loan Payment', 'Financial:Money Transfers', 'Financial:Other Financial', 'Financial:Tax Preparation', 'Financial:Taxes, Federal', 'Financial:Taxes, Other', 'Financial:Taxes, State', 'Food & Drink:Alcohol & Bars', 'Food & Drink:Coffee & Tea', 'Food & Drink:Dessert', 'Food & Drink:Fast Food', 'Food & Drink:Groceries', 'Food & Drink:Other Food & Drink', 'Food & Drink:Restaurants', 'Food & Drink:Snacks', 'Food & Drink:Tobacco & Like', 'Gifts & Donations:Charities', 'Gifts & Donations:Gifts', 'Health & Medical:Care Facilities', 'Health & Medical:Dentist', 'Health & Medical:Doctor', 'Health & Medical:Equipment', 'Health & Medical:Eyes', 'Health & Medical:Health Insurance', 'Health & Medical:Other Health & Medical', 'Health & Medical:Pharmacies', 'Health & Medical:Prescriptions', 'Home:Furnishings', 'Home:Home Insurance', 'Home:Home Purchase', 'Home:Home Services', 'Home:Home Supplies', 'Home:Lawn & Garden', 'Home:Mortgage', 'Home:Moving', 'Home:Other Home', 'Home:Property Tax', 'Home:Rent', "Home:Renter's Insurance", 'Income:Bonus', 'Income:Commission', 'Income:Interest', 'Income:Other Income', 'Income:Paycheck', 'Income:Reimbursement', 'Income:Rental Income', 'Investment:Education Investment', 'Investment:Other Investments', 'Investment:Retirement', 'Investment:Stocks & Mutual Funds', 'Legal:Legal Fees', 'Legal:Legal Services', 'Legal:Other Legal Costs', 'Office:Equipment', 'Office:Office Supplies', 'Office:Other Office', 'Office:Postage & Shipping', 'Personal:Accessories', 'Personal:Beauty', 'Personal:Body Enhancement', 'Personal:Clothing', 'Personal:Counseling', 'Personal:Hair', 'Personal:Hobbies', 'Personal:Jewelry', 'Personal:Laundry', 'Personal:Other Personal', 'Personal:Religion', 'Personal:Shoes', 'Pets:Pet Food', 'Pets:Pet Grooming', 'Pets:Pet Medicine', 'Pets:Pet Supplies', 'Pets:Veterinarian', 'Sports & Fitness:Camping', 'Sports & Fitness:Fitness Gear', 'Sports & Fitness:Golf', 'Sports & Fitness:Memberships', 'Sports & Fitness:Other Sports & Fitness', 'Sports & Fitness:Sporting Events', 'Sports & Fitness:Sporting Goods', 'Technology:Domains & Hosting', 'Technology:Hardware', 'Technology:Online Services', 'Technology:Software', 'Transportation:Auto Insurance', 'Transportation:Auto Payment', 'Transportation:Auto Services', 'Transportation:Auto Supplies', 'Transportation:Bicycle', 'Transportation:Boats & Marine', 'Transportation:Gas', 'Transportation:Other Transportation', 'Transportation:Parking & Tolls', 'Transportation:Parking Tickets', 'Transportation:Public Transit', 'Transportation:Shipping', 'Transportation:Taxies', 'Travel:Car Rental', 'Travel:Flights', 'Travel:Hotels', 'Travel:Tours & Cruises', 'Travel:Train', 'Travel:Travel Buses', 'Travel:Travel Dining', 'Travel:Travel Entertainment', 'Uncategorized:Cash', 'Uncategorized:Other Shopping', 'Uncategorized:Unknown', 'Uncategorized:Unassigned', 'Utilities:Cable', 'Utilities:Electricity', 'Utilities:Gas & Fuel', 'Utilities:Internet', 'Utilities:Other Utilities', 'Utilities:Phone', 'Utilities:Trash', 'Utilities:Water & Sewer']
- **`memo`** (`string`)
- **`created_at`** (`string`) *(required, read-only)*
- **`modified_at`** (`string`) *(required, read-only)*

### TransactionRequest

Serializer for bank transactions.

On create the caller supplies bank_account, amount,
transaction_date, transaction_type, raw_description, and
optionally pending, memo, and description.

After creation only transaction_type, memo, and description are
updatable.  The view is responsible for creating the default
TransactionAllocation to the unallocated budget on create.

The ``amount_currency`` is read from raw request data by
djmoney's ``MoneyField.get_value()`` -- no explicit currency
field declaration is needed.

- **`bank_account`** (`string`) *(required)*
- **`amount`** (`string`) *(required)*
- **`transaction_date`** (`string`) *(required)*
- **`transaction_type`** (``) *(required)*
- **`pending`** (`boolean`)
- **`memo`** (`string`)
- **`raw_description`** (`string`) *(required)*
- **`description`** (`string`)
- **`image`** (`string`)
- **`document`** (`string`)

### TransactionSplitsRequest

Serializer for the declarative splits endpoint.

Accepts a dict mapping budget UUIDs to amounts.  The backend
reconciles existing allocations to match the declared state.
Any remainder goes to the unallocated budget.

All budgets must belong to the same bank account as the
transaction.  Cross-account budget references are rejected
with a 400 error.

- **`splits`** (`object`) *(required)* — Map of budget UUID → amount.  Amounts must not exceed the transaction total.  Omitted remainder is assigned to the unallocated budget.

### TransactionTypeEnum

* `signature_purchase` - Signature Purchase
* `ach` - ACH
* `round-up_transfer` - Round-up Transfer
* `protected_goal_account_transfer` - Protected Goal Account Transfer
* `fee` - Fee
* `pin_purchase` - Pin Purchase
* `signature_credit` - Signature Credit
* `interest_credit` - Interest Credit
* `shared_transfer` - Shared Transfer
* `courtesy_credit` - Courtesy Credit
* `atm_withdrawal` - ATM Withdrawal
* `bill_payment` - Bill Payment
* `bank_generated_credit` - Bank Generated Credit
* `wire_transfer` - Wire Transfer
* `check_deposit` - Check Deposit
* `check` - Check
* `c2c` - c2c
* `migration_interbank_transfer` - Migration Interbank Transfer
* `balance_sweep` - Balance Sweep
* `ach_reversal` - ACH Reversal
* `adjustment` - Adjustment
* `signature_return` - Signature return
* `fx_order` - FX Order
* `` - --------


### User

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

### UserRequest

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)


# mibudge API

REST API for managing bank accounts, budgets, transactions, and budget allocations in the mibudge personal budgeting service.

**Version:** 1.0.0

## Authentication

- **jwtAuth**: `http` (in: ``, name: ``)

## Endpoints

### token

#### `POST /api/token/refresh/`

**Operation:** `token_refresh_create`

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

### users

#### `GET /api/users/`

**Operation:** `users_list`

**Parameters:**

- `page` (query, optional) — A page number within the paginated result set.

**Response 200:** 

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

#### `GET /api/users/{username}/`

**Operation:** `users_retrieve`

**Parameters:**

- `username` (path, required)

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

#### `PUT /api/users/{username}/`

**Operation:** `users_update`

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

#### `PATCH /api/users/{username}/`

**Operation:** `users_partial_update`

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

#### `GET /api/users/me/`

**Operation:** `users_me_retrieve`

**Response 200:** 

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

## Schemas

### PaginatedUserList

- **`count`** (`integer`) *(required)*
- **`next`** (`string`)
- **`previous`** (`string`)
- **`results`** (`array`) *(required)*

### PatchedUserRequest

- **`username`** (`string`) — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)

### TokenRefresh

- **`access`** (`string`) *(required, read-only)*
- **`refresh`** (`string`) *(required)*

### TokenRefreshRequest

- **`refresh`** (`string`) *(required)*

### User

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)
- **`url`** (`string`) *(required, read-only)*

### UserRequest

- **`username`** (`string`) *(required)* — Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.
- **`name`** (`string`)


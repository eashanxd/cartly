# 🛒 Cartly

A modern, dark-themed e-commerce storefront built with **Python, Flask, Jinja2, HTML, CSS, and JavaScript**, powered by the **DummyJSON Products API**.

Cartly allows users to browse products, search and filter the catalog, view product details, and manage a session-based shopping cart.

---

## ✨ Features

### 🛍️ Product Catalog

- Live product data from the DummyJSON API
- Product listings with:
  - Name
  - Price
  - Rating
  - Category
  - Brand
  - Discount
  - Stock
  - Images
- Individual product detail pages
- Product image galleries
- Dynamic product categories

### 🔎 Product Discovery

- Product search
- Category filtering
- Price sorting
- Rating sorting
- Alphabetical sorting
- Search + category filtering
- Pagination
- Product count
- Empty search-result states

### 🛒 Shopping Cart

- Add products to cart
- Increase/decrease quantities
- Direct quantity updates
- Remove products
- Session-based cart
- Cart item count
- Automatic subtotal calculation
- Stock validation
- Multiple products in cart
- Empty cart state
- Server-side cart calculations

### 🎨 UI / UX

- Modern dark theme
- Responsive design
- Desktop, tablet, and mobile layouts
- Responsive navigation
- Product cards
- Product discount badges
- Rating indicators
- Toast notifications
- Loading and error states
- Custom 404 page
- Accessible controls
- Subtle hover animations
- Mobile-friendly product browsing

### 🛡️ Error Handling

The application handles:

- Invalid product IDs
- Empty searches
- No search results
- Invalid quantities
- Out-of-stock products
- API failures
- API timeouts
- Missing product data
- Empty cart

---

## 🧰 Tech Stack

### Backend

- **Python**
- **Flask**
- **Requests**
- **Jinja2**

### Frontend

- **HTML5**
- **CSS3**
- **Vanilla JavaScript**

### External API

- **DummyJSON Products API**

### Testing

- **Python testing tools**
- Automated Flask application tests

---

## 🏗️ Architecture

Cartly follows a simple API-driven architecture:

```text
                    ┌─────────────────┐
                    │     Browser     │
                    │  HTML/CSS/JS    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Flask Backend  │
                    └────────┬────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
        ┌─────────────────┐     ┌─────────────────┐
        │ Product Service │     │ Flask Session   │
        └────────┬────────┘     │     Cart        │
                 │              └─────────────────┘
                 ▼
        ┌─────────────────┐
        │   DummyJSON     │
        │   Products API  │
        └─────────────────┘
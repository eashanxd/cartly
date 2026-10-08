import unittest
from decimal import Decimal
from unittest.mock import patch

import requests

from app import create_app
from services.products import clear_cache


def api_product(product_id, title, category, price, rating, stock=10, **overrides):
    product = {
        "id": product_id,
        "title": title,
        "description": f"Detailed description for {title}",
        "category": category,
        "price": price,
        "rating": rating,
        "stock": stock,
        "brand": f"Brand {product_id}",
        "thumbnail": f"https://cdn.dummyjson.com/products/{product_id}/thumbnail.webp",
        "images": [f"https://cdn.dummyjson.com/products/{product_id}/1.webp"],
        "discountPercentage": 10,
    }
    product.update(overrides)
    return product


TEST_PRODUCTS = [
    api_product(1, "Phone Alpha", "smartphones", "10.25", 4.2, stock=3),
    api_product(2, "Phone Beta", "mobile-accessories", "20.99", 4.8),
    api_product(3, "Laptop Gamma", "laptops", "120.50", 4.9),
    api_product(4, "Phone Case Delta", "mobile-accessories", "8.00", 3.7),
] + [
    api_product(
        product_id,
        f"Catalog item {product_id:02d}",
        ("smartphones", "laptops", "beauty")[product_id % 3],
        f"{product_id + 10}.00",
        3 + (product_id % 20) / 10,
    )
    for product_id in range(5, 67)
]

TEST_CATEGORIES = [
    {"slug": "smartphones", "name": "Smartphones", "url": "https://dummyjson.com/products/category/smartphones"},
    {"slug": "mobile-accessories", "name": "Mobile Accessories", "url": "https://dummyjson.com/products/category/mobile-accessories"},
    {"slug": "laptops", "name": "Laptops", "url": "https://dummyjson.com/products/category/laptops"},
    {"slug": "beauty", "name": "Beauty", "url": "https://dummyjson.com/products/category/beauty"},
]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class CartlyAppTests(unittest.TestCase):
    def setUp(self):
        clear_cache()
        self.api_calls = []
        self.api_patch = patch("services.products.requests.get", side_effect=self.fake_api_get)
        self.api_patch.start()
        self.addCleanup(self.api_patch.stop)
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test-secret"})
        self.client = self.app.test_client()

    def fake_api_get(self, url, params=None, timeout=None):
        params = params or {}
        self.api_calls.append((url, params.copy(), timeout))
        if url.endswith("/categories"):
            return FakeResponse(TEST_CATEGORIES)
        if url.endswith("/search"):
            query = params.get("q", "").casefold()
            results = [
                product for product in TEST_PRODUCTS
                if any(
                    query in str(product.get(field, "")).casefold()
                    for field in ("title", "description", "category", "brand")
                )
            ]
        elif "/category/" in url:
            slug = url.rsplit("/", 1)[-1]
            results = [product for product in TEST_PRODUCTS if product["category"] == slug]
        elif url.rstrip("/").rsplit("/", 1)[-1].isdigit():
            product_id = int(url.rstrip("/").rsplit("/", 1)[-1])
            product = next((item for item in TEST_PRODUCTS if item["id"] == product_id), None)
            if product is None:
                return FakeResponse({"message": "Product not found"}, 404)
            return FakeResponse(product)
        else:
            results = list(TEST_PRODUCTS)

        sort_by = params.get("sortBy")
        order = params.get("order", "asc")
        if sort_by:
            if sort_by in {"price", "rating"}:
                results.sort(
                    key=lambda product: float(product.get(sort_by, 0)),
                    reverse=order == "desc",
                )
            else:
                results.sort(key=lambda product: product.get(sort_by, ""), reverse=order == "desc")
        total = len(results)
        skip = int(params.get("skip", 0))
        limit = int(params.get("limit", 30))
        if limit:
            results = results[skip : skip + limit]
        return FakeResponse({"products": results, "total": total, "skip": skip, "limit": limit})

    def test_home_loads_api_products_and_dynamic_categories(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="hero-search"', response.data)
        self.assertIn(b"Laptop Gamma", response.data)
        self.assertIn(b"Smartphones", response.data)
        self.assertIn(b"Mobile Accessories", response.data)
        self.assertTrue(any(url.endswith("/categories") for url, _, _ in self.api_calls))
        self.assertTrue(any(url.endswith("/products") for url, _, _ in self.api_calls))

    def test_search_uses_api_search_and_normalizes_query(self):
        response = self.client.get("/products?search=%20PHONE%20")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Phone Alpha", response.data)
        self.assertIn(b"Phone Beta", response.data)
        self.assertTrue(any(url.endswith("/search") and params.get("q") == "PHONE" for url, params, _ in self.api_calls))

        response = self.client.get("/products?search=case")
        self.assertIn(b"Phone Case Delta", response.data)

    def test_category_and_combined_search_category_use_api(self):
        response = self.client.get("/products?category=mobile-accessories")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Phone Beta", response.data)
        self.assertNotIn(b"Phone Alpha", response.data)
        self.assertTrue(any("/category/mobile-accessories" in url for url, _, _ in self.api_calls))

        self.api_calls.clear()
        response = self.client.get("/products?search=phone&category=mobile-accessories")
        self.assertIn(b"Phone Beta", response.data)
        self.assertIn(b"Phone Case Delta", response.data)
        self.assertNotIn(b"Phone Alpha", response.data)
        self.assertIn("mobile-accessories", response.data.decode())
        self.assertTrue(any(url.endswith("/search") for url, _, _ in self.api_calls))

    def test_sorting_is_correct_and_pagination_preserves_filters(self):
        low_to_high = self.client.get("/products?category=mobile-accessories&sort=price_asc")
        self.assertLess(low_to_high.data.index(b"Phone Case Delta"), low_to_high.data.index(b"Phone Beta"))
        high_to_low = self.client.get("/products?category=mobile-accessories&sort=price_desc")
        self.assertLess(high_to_low.data.index(b"Phone Beta"), high_to_low.data.index(b"Phone Case Delta"))
        rating = self.client.get("/products?sort=rating")
        self.assertLess(rating.data.index(b"Laptop Gamma"), rating.data.index(b"Phone Beta"))
        name = self.client.get("/products?sort=name")
        self.assertLess(name.data.index(b"Catalog item 05"), name.data.index(b"Catalog item 06"))

        page = self.client.get("/products?search=catalog&category=smartphones&page=2&sort=name")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Previous", page.data)
        self.assertIn(b"search=catalog", page.data)
        self.assertIn(b"category=smartphones", page.data)

    def test_empty_search_and_invalid_category_are_graceful(self):
        self.assertEqual(self.client.get("/products?search=").status_code, 200)
        empty = self.client.get("/products?search=not-a-match")
        self.assertEqual(empty.status_code, 200)
        self.assertIn(b"No products found.", empty.data)
        invalid = self.client.get("/products?category=not-a-real-category")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(b"category is no longer available", invalid.data)

    def test_product_details_normalize_api_data_and_invalid_ids_404(self):
        response = self.client.get("/product/1")
        self.assertEqual(response.status_code, 200)
        for field in (b"Phone Alpha", b"BRAND 1", b"SMARTPHONES", b"$11.39", b"10% OFF", b"thumbnail.webp"):
            self.assertIn(field, response.data)
        self.assertTrue(any(url.endswith("/products/1") for url, _, _ in self.api_calls))
        missing = self.client.get("/product/99999")
        self.assertEqual(missing.status_code, 404)

    def test_cart_snapshots_api_products_and_calculates_decimal_totals(self):
        self.client.post("/cart/add/1", data={"quantity": "2"})
        self.client.post("/cart/add/1")
        self.client.post("/cart/add/2")
        response = self.client.get("/cart")
        self.assertIn(b"$10.25 each", response.data)
        self.assertIn(b"$30.75", response.data)
        self.assertIn(b"$20.99", response.data)
        self.assertIn(b"$51.74", response.data)
        self.assertIn(b"<span>4</span>", response.data)
        self.assertEqual(response.status_code, 200)

    def test_cart_increase_decrease_remove_and_zero(self):
        self.client.post("/cart/add/1")
        self.client.post("/cart/increase/1")
        self.assertIn(b'value="2"', self.client.get("/cart").data)
        self.client.post("/cart/decrease/1")
        self.assertIn(b'value="1"', self.client.get("/cart").data)
        self.client.post("/cart/decrease/1")
        self.assertIn(b"Your cart is empty.", self.client.get("/cart").data)
        self.client.post("/cart/add/1")
        self.client.post("/cart/remove/1")
        self.assertIn(b"Your cart is empty.", self.client.get("/cart").data)

    def test_stock_and_quantity_validation(self):
        self.client.post("/cart/add/1", data={"quantity": "3"})
        self.client.post("/cart/add/1", data={"quantity": "1"})
        self.assertIn(b"Only 3 units available.", self.client.get("/cart").data)
        self.client.post("/cart/update/1", data={"quantity": "4"})
        self.assertIn(b"Only 3 units available.", self.client.get("/cart").data)
        self.client.post("/cart/add/2", data={"quantity": "0"})
        self.client.post("/cart/add/2", data={"quantity": "bad"})
        self.assertIn(b"Please enter a valid quantity.", self.client.get("/cart").data)
        self.client.post("/cart/add/1", data={"quantity": "-1"})
        self.assertIn(b"Quantity must be at least 1.", self.client.get("/cart").data)

    def test_cart_survives_api_failure_and_product_disappearance_is_cleaned(self):
        self.client.post("/cart/add/1")
        with patch("services.products.requests.get", side_effect=requests.Timeout):
            response = self.client.post("/cart/increase/1", follow_redirects=True)
            self.assertIn(b"temporarily unavailable", response.data)
            self.assertIn(b'value="1"', response.data)

        with patch("services.products.requests.get", side_effect=self.missing_product_api):
            response = self.client.post("/cart/increase/1", follow_redirects=True)
            self.assertIn(b"no longer available", response.data)
            self.assertIn(b"Your cart is empty.", response.data)

    def missing_product_api(self, url, params=None, timeout=None):
        if url.endswith("/categories"):
            return FakeResponse(TEST_CATEGORIES)
        return FakeResponse({"message": "Product not found"}, 404)

    def test_api_failure_shows_graceful_catalog_state(self):
        with patch("services.products.requests.get", side_effect=requests.Timeout):
            response = self.client.get("/products")
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"catalog is temporarily unavailable", response.data)
        self.assertNotIn(b"Traceback", response.data)


if __name__ == "__main__":
    unittest.main()

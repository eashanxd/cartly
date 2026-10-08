"""DummyJSON product catalog client and Cartly product normalization."""

import logging
import threading
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests


API_BASE_URL = "https://dummyjson.com/products"
REQUEST_TIMEOUT = (3.05, 8)
PAGE_SIZE = 12
CATEGORY_CACHE_SECONDS = 300
logger = logging.getLogger(__name__)
_category_cache = {"expires_at": 0.0, "value": None}
_cache_lock = threading.Lock()


class ProductServiceError(Exception):
    """Raised when the product API cannot be used or returns invalid data."""


class ProductNotFound(ProductServiceError):
    """Raised when DummyJSON has no product with the requested ID."""


class InvalidCategory(ProductServiceError):
    """Raised when a selected category is not in DummyJSON's category list."""


def clear_cache():
    """Clear the process-local category cache (also useful for isolated tests)."""
    with _cache_lock:
        _category_cache["expires_at"] = 0.0
        _category_cache["value"] = None


def _request_json(url, params=None):
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            raise ProductNotFound("The requested product was not found.")
        response.raise_for_status()
        payload = response.json()
    except ProductNotFound:
        raise
    except (requests.RequestException, ValueError) as exc:
        logger.warning("DummyJSON request failed for %s: %s", url, exc)
        raise ProductServiceError("The product catalog is temporarily unavailable.") from exc
    if not isinstance(payload, dict) and not isinstance(payload, list):
        logger.warning("DummyJSON returned an unexpected response for %s", url)
        raise ProductServiceError("The product catalog returned an invalid response.")
    return payload


def _safe_decimal(value, default="0.00"):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_product(raw):
    """Map a DummyJSON product to the stable Cartly template/session shape."""
    if not isinstance(raw, dict):
        raise ProductServiceError("The product catalog returned an invalid product.")
    try:
        product_id = int(raw["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProductServiceError("The product catalog returned a product without an ID.") from exc

    images = raw.get("images")
    if not isinstance(images, list):
        images = []
    images = [image for image in images if isinstance(image, str) and image.strip()]
    thumbnail = raw.get("thumbnail")
    image = thumbnail if isinstance(thumbnail, str) and thumbnail.strip() else (images[0] if images else "")
    title = raw.get("title")
    category = raw.get("category")

    return {
        "id": product_id,
        "name": title.strip() if isinstance(title, str) and title.strip() else "Untitled product",
        "description": raw.get("description") if isinstance(raw.get("description"), str) else "",
        "category": category.strip() if isinstance(category, str) and category.strip() else "Uncategorized",
        "price": _safe_decimal(raw.get("price")),
        "rating": _safe_decimal(raw.get("rating")),
        "stock": max(0, _safe_int(raw.get("stock", 0))),
        "brand": raw.get("brand") if isinstance(raw.get("brand"), str) and raw.get("brand") else "Brand not specified",
        "image": image,
        "images": images,
        "discount": _safe_decimal(raw.get("discountPercentage")),
    }


def get_categories():
    """Fetch and briefly cache DummyJSON's category records."""
    now = time.monotonic()
    with _cache_lock:
        cached = _category_cache["value"]
        if cached is not None and now < _category_cache["expires_at"]:
            return list(cached)

    payload = _request_json(f"{API_BASE_URL}/categories")
    if not isinstance(payload, list):
        raise ProductServiceError("The product catalog returned invalid categories.")

    categories = []
    for category in payload:
        if isinstance(category, dict):
            slug = category.get("slug")
            name = category.get("name")
        else:
            slug = category
            name = category
        if isinstance(slug, str) and slug.strip():
            categories.append(
                {
                    "slug": slug.strip(),
                    "name": name.strip() if isinstance(name, str) and name.strip() else slug.strip(),
                }
            )

    with _cache_lock:
        _category_cache["value"] = categories
        _category_cache["expires_at"] = time.monotonic() + CATEGORY_CACHE_SECONDS
    return list(categories)


def _sort_parameters(sort):
    return {
        "price_asc": ("price", "asc"),
        "price_desc": ("price", "desc"),
        "rating": ("rating", "desc"),
        "name": ("title", "asc"),
    }.get(sort)


def _normalize_list_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise ProductServiceError("The product catalog returned an invalid product list.")
    products = []
    for raw in payload["products"]:
        try:
            products.append(normalize_product(raw))
        except ProductServiceError:
            logger.warning("Skipping malformed product record from DummyJSON")
    return products, max(0, _safe_int(payload.get("total"), len(products)))


def list_products(search="", category="", sort="default", page=1, limit=PAGE_SIZE):
    """Fetch one API-backed product page; intersect search/category if both selected."""
    search = search.strip()
    page = max(1, int(page))
    limit = max(1, int(limit))
    skip = (page - 1) * limit
    sort_params = _sort_parameters(sort)

    if category and search:
        category_slugs = {item["slug"] for item in get_categories()}
        if category not in category_slugs:
            raise InvalidCategory(category)
        params = {"q": search, "limit": 0}
        if sort_params:
            params.update({"sortBy": sort_params[0], "order": sort_params[1]})
        payload = _request_json(f"{API_BASE_URL}/search", params=params)
        products, _ = _normalize_list_payload(payload)
        filtered = [product for product in products if product["category"] == category]
        if sort_params:
            filtered = _sort_products(filtered, sort)
        total = len(filtered)
        return filtered[skip : skip + limit], total

    if category:
        category_slugs = {item["slug"] for item in get_categories()}
        if category not in category_slugs:
            raise InvalidCategory(category)
        endpoint = f"{API_BASE_URL}/category/{quote(category, safe='')}"
        params = {"limit": limit, "skip": skip}
    elif search:
        endpoint = f"{API_BASE_URL}/search"
        params = {"q": search, "limit": limit, "skip": skip}
    else:
        endpoint = API_BASE_URL
        params = {"limit": limit, "skip": skip}

    if sort_params:
        params.update({"sortBy": sort_params[0], "order": sort_params[1]})
    payload = _request_json(endpoint, params=params)
    return _normalize_list_payload(payload)


def _sort_products(products, sort):
    if sort == "price_asc":
        return sorted(products, key=lambda product: (product["price"], product["name"].casefold()))
    if sort == "price_desc":
        return sorted(products, key=lambda product: (-product["price"], product["name"].casefold()))
    if sort == "rating":
        return sorted(products, key=lambda product: (-product["rating"], product["name"].casefold()))
    if sort == "name":
        return sorted(products, key=lambda product: product["name"].casefold())
    return products


def get_product(product_id):
    payload = _request_json(f"{API_BASE_URL}/{int(product_id)}")
    if not isinstance(payload, dict):
        raise ProductServiceError("The product catalog returned an invalid product.")
    return normalize_product(payload)


def get_featured_products(limit=4):
    """Use the API's highest-rated products as the homepage featured selection."""
    products, _total = list_products(sort="rating", page=1, limit=limit)
    return products


def to_cart_product(product):
    """Keep only safe, stable product data needed to render a session cart."""
    return {
        "id": int(product["id"]),
        "name": str(product["name"]),
        "category": str(product["category"]),
        "price": str(_safe_decimal(product["price"])),
        "stock": max(0, int(product["stock"])),
        "brand": str(product["brand"]),
        "image": str(product["image"]),
    }

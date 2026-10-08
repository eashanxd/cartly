import logging
import os
from decimal import Decimal
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from services.products import (
    InvalidCategory,
    ProductNotFound,
    ProductServiceError,
    get_categories,
    get_featured_products,
    get_product,
    list_products,
    to_cart_product,
)

PAGE_SIZE = 12


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "cartly-local-development-key"),
    )
    if test_config:
        app.config.update(test_config)

    @app.context_processor
    def inject_cart_count():
        cart = session.get("cart", {})
        if not isinstance(cart, dict):
            cart = {}
        count = sum(
            entry.get("quantity", 0)
            for entry in cart.values()
            if isinstance(entry, dict)
            and isinstance(entry.get("quantity"), int)
            and not isinstance(entry.get("quantity"), bool)
            and entry["quantity"] > 0
        )
        return {"cart_count": count}

    def redirect_to_previous_page(fallback):
        referrer = request.referrer
        if referrer and urlsplit(referrer).netloc == request.host:
            return redirect(referrer)
        return redirect(fallback)

    def read_cart():
        stored_cart = session.get("cart", {})
        if not isinstance(stored_cart, dict):
            session["cart"] = {}
            return {}
        cart = {}
        for product_id, entry in stored_cart.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("product"), dict):
                continue
            quantity = entry.get("quantity")
            try:
                product = to_cart_product(entry["product"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                not isinstance(quantity, int)
                or isinstance(quantity, bool)
                or quantity < 1
                or product["stock"] < 1
            ):
                continue
            quantity = min(quantity, product["stock"])
            cart[str(product["id"])] = {"product": product, "quantity": quantity}
        if cart != stored_cart:
            session["cart"] = cart
        return cart

    def get_cart_lines():
        cart = read_cart()
        lines = []
        subtotal = Decimal("0.00")
        for entry in cart.values():
            product = entry["product"]
            quantity = entry["quantity"]
            line_subtotal = (Decimal(product["price"]) * quantity).quantize(Decimal("0.01"))
            subtotal += line_subtotal
            display_product = dict(product)
            display_product["price"] = Decimal(product["price"])
            lines.append(
                {
                    "product": display_product,
                    "quantity": quantity,
                    "subtotal": line_subtotal,
                }
            )
        return lines, subtotal

    def catalog_error_response(message, status_code=503, **context):
        return (
            render_template("catalog_error.html", catalog_error=message, **context),
            status_code,
        )

    @app.get("/")
    def index():
        categories = []
        featured_products = []
        errors = []
        try:
            categories = get_categories()
        except ProductServiceError:
            app.logger.exception("Could not load categories for homepage")
            errors.append("Product categories are temporarily unavailable.")
        try:
            featured_products = get_featured_products()
        except ProductServiceError:
            app.logger.exception("Could not load featured products for homepage")
            errors.append("Featured products are temporarily unavailable.")
        return (
            render_template(
                "index.html",
                categories=categories,
                featured_products=featured_products,
                catalog_error=" ".join(errors),
            ),
            503 if errors else 200,
        )

    @app.get("/products")
    def products():
        search_query = request.args.get("search", request.args.get("q", "")).strip()
        selected_category = request.args.get("category", "").strip()
        sort_by = request.args.get("sort", "default")
        categories = []
        try:
            categories = get_categories()
            page = max(1, int(request.args.get("page", "1")))
            products, total = list_products(
                search=search_query,
                category=selected_category,
                sort=sort_by,
                page=page,
                limit=PAGE_SIZE,
            )
        except ValueError:
            page = 1
            products, total = [], 0
            categories = []
            catalog_error = "Choose a valid page number."
            return render_template(
                "products.html",
                products=products,
                total=total,
                page=page,
                page_count=0,
                categories=categories,
                search_query=search_query,
                selected_category=selected_category,
                sort_by=sort_by,
                catalog_error=catalog_error,
            ), 400
        except InvalidCategory:
            app.logger.info("Unknown DummyJSON category requested: %s", selected_category)
            return render_template(
                "products.html",
                products=[],
                total=0,
                page=1,
                page_count=0,
                categories=categories,
                search_query=search_query,
                selected_category=selected_category,
                sort_by=sort_by,
                catalog_error="That category is no longer available. Choose another category.",
            ), 400
        except ProductServiceError:
            app.logger.exception("Could not load the product listing")
            return render_template(
                "products.html",
                products=[],
                total=0,
                page=1,
                page_count=0,
                categories=[],
                search_query=search_query,
                selected_category=selected_category,
                sort_by=sort_by,
                catalog_error="The product catalog is temporarily unavailable. Please try again.",
            ), 503

        page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
        return render_template(
            "products.html",
            products=products,
            total=total,
            page=page,
            page_count=page_count,
            categories=categories,
            search_query=search_query,
            selected_category=selected_category,
            sort_by=sort_by,
            catalog_error="",
        )

    @app.get("/product/<int:product_id>")
    def product_detail(product_id):
        try:
            product = get_product(product_id)
        except ProductNotFound:
            abort(404)
        except ProductServiceError:
            app.logger.exception("Could not load product %s from DummyJSON", product_id)
            return catalog_error_response(
                "Product details are temporarily unavailable. Please try again.",
                503,
            )
        return render_template("product.html", product=product)

    @app.get("/cart")
    def cart():
        lines, subtotal = get_cart_lines()
        total_quantity = sum(line["quantity"] for line in lines)
        return render_template(
            "cart.html",
            cart_lines=lines,
            subtotal=subtotal,
            total_quantity=total_quantity,
        )

    @app.post("/cart/add/<int:product_id>")
    def add_to_cart(product_id):
        try:
            product = get_product(product_id)
        except ProductNotFound:
            abort(404)
        except ProductServiceError:
            app.logger.exception("Could not validate product %s before adding to cart", product_id)
            flash("The product catalog is temporarily unavailable. Please try again.", "error")
            return redirect_to_previous_page(url_for("products"))

        try:
            quantity = int(request.form.get("quantity", "1"))
        except (TypeError, ValueError):
            flash("Please enter a valid quantity.", "error")
            return redirect_to_previous_page(url_for("product_detail", product_id=product_id))
        if quantity < 1:
            flash("Quantity must be at least 1.", "error")
            return redirect_to_previous_page(url_for("product_detail", product_id=product_id))
        if product["stock"] < 1:
            flash(f"{product['name']} is currently out of stock.", "error")
            return redirect_to_previous_page(url_for("product_detail", product_id=product_id))

        cart_items = read_cart()
        existing = cart_items.get(str(product_id), {}).get("quantity", 0)
        if existing + quantity > product["stock"]:
            flash(f"Only {product['stock']} units available.", "error")
            return redirect_to_previous_page(url_for("product_detail", product_id=product_id))
        cart_items[str(product_id)] = {
            "product": to_cart_product(product),
            "quantity": existing + quantity,
        }
        session["cart"] = cart_items
        flash(f"{product['name']} added to your cart.", "success")
        return redirect_to_previous_page(url_for("cart"))

    @app.post("/cart/remove/<int:product_id>")
    def remove_from_cart(product_id):
        cart_items = read_cart()
        if str(product_id) in cart_items:
            cart_items.pop(str(product_id))
            session["cart"] = cart_items
            flash("Product removed from your cart.", "success")
        else:
            flash("That product is not in your cart.", "error")
        return redirect(url_for("cart"))

    def change_cart_quantity(product_id, change=None, new_quantity=None):
        cart_items = read_cart()
        key = str(product_id)
        if key not in cart_items:
            flash("That product is not in your cart.", "error")
            return redirect(url_for("cart"))
        try:
            product = get_product(product_id)
        except ProductNotFound:
            cart_items.pop(key, None)
            session["cart"] = cart_items
            flash("This product is no longer available and was removed from your cart.", "error")
            return redirect(url_for("cart"))
        except ProductServiceError:
            app.logger.exception("Could not validate cart product %s", product_id)
            flash("The product catalog is temporarily unavailable. Your cart was not changed.", "error")
            return redirect(url_for("cart"))

        current_quantity = cart_items[key]["quantity"]
        if product["stock"] < 1:
            cart_items.pop(key, None)
            session["cart"] = cart_items
            flash(f"{product['name']} is out of stock and was removed from your cart.", "error")
            return redirect(url_for("cart"))
        cart_items[key]["product"] = to_cart_product(product)
        quantity = new_quantity if new_quantity is not None else current_quantity + change
        if quantity <= 0:
            cart_items.pop(key, None)
            flash(f"{product['name']} removed from your cart.", "success")
        elif quantity > product["stock"]:
            flash(f"Only {product['stock']} units available.", "error")
        else:
            cart_items[key]["quantity"] = quantity
            flash(f"{product['name']} quantity updated.", "success")
        session["cart"] = cart_items
        return redirect(url_for("cart"))

    @app.post("/cart/increase/<int:product_id>")
    def increase_cart_quantity(product_id):
        return change_cart_quantity(product_id, change=1)

    @app.post("/cart/decrease/<int:product_id>")
    def decrease_cart_quantity(product_id):
        return change_cart_quantity(product_id, change=-1)

    @app.post("/cart/update/<int:product_id>")
    def update_cart(product_id):
        try:
            quantity = int(request.form.get("quantity", ""))
        except (TypeError, ValueError):
            flash("Please enter a valid quantity.", "error")
            return redirect(url_for("cart"))
        if quantity < 1:
            flash("Quantity must be at least 1.", "error")
            return redirect(url_for("cart"))
        return change_cart_quantity(product_id, new_quantity=quantity)

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(_error):
        app.logger.exception("Unhandled Cartly request error")
        return render_template("500.html"), 500

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=False)

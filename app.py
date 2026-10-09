import sqlite3
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import uuid

app = Flask(__name__)

app.secret_key = "nexora-dev-secret-change-this-later"


def get_db_connection():
    connection = sqlite3.connect("store.db")
    connection.row_factory = sqlite3.Row
    return connection


def get_or_create_cart(connection):
    if "cart_session_id" not in session:
        session["cart_session_id"] = str(uuid.uuid4())

    cart_session_id = session["cart_session_id"]

    cart = connection.execute(
        "SELECT * FROM carts WHERE session_id = ?", (cart_session_id,)
    ).fetchone()

    if cart is None:
        connection.execute(
            "INSERT INTO carts (session_id) VALUES (?)", (cart_session_id,)
        )
        connection.commit()
        cart = connection.execute(
            "SELECT * FROM carts WHERE session_id = ?", (cart_session_id,)
        ).fetchone()

    return cart


@app.context_processor
def inject_cart_count():
    connection = get_db_connection()
    cart = get_or_create_cart(connection)
    result = connection.execute(
        "SELECT SUM(quantity) as total FROM cart_items WHERE cart_id = ?",
        (cart["id"],)
    ).fetchone()
    connection.close()
    return {"cart_count": result["total"] or 0}


@app.route("/add-to-cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    connection = get_db_connection()
    cart = get_or_create_cart(connection)

    product = connection.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()

    if product is None:
        connection.close()
        return jsonify({"error": "Product not found"}), 404

    existing_item = connection.execute(
        "SELECT * FROM cart_items WHERE cart_id = ? AND product_id = ?",
        (cart["id"], product_id)
    ).fetchone()

    if existing_item:
        connection.execute(
            "UPDATE cart_items SET quantity = quantity + 1 WHERE id = ?",
            (existing_item["id"],)
        )
    else:
        connection.execute(
            "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)",
            (cart["id"], product_id, 1)
        )

    connection.commit()

    cart_count = connection.execute(
        "SELECT SUM(quantity) as total FROM cart_items WHERE cart_id = ?",
        (cart["id"],)
    ).fetchone()

    connection.close()

    return jsonify({"success": True, "cart_count": cart_count["total"] or 0})


@app.route("/cart")
def view_cart():
    connection = get_db_connection()
    cart = get_or_create_cart(connection)

    items = connection.execute("""
        SELECT cart_items.id, cart_items.quantity,
               products.id as product_id, products.name,
               products.price, products.stock_quantity
        FROM cart_items
        JOIN products ON cart_items.product_id = products.id
        WHERE cart_items.cart_id = ?
    """, (cart["id"],)).fetchall()

    connection.close()

    total = sum(item["price"] * item["quantity"] for item in items)

    return render_template("cart.html", items=items, total=total)


@app.route("/remove-from-cart/<int:item_id>", methods=["POST"])
def remove_from_cart(item_id):
    connection = get_db_connection()
    connection.execute("DELETE FROM cart_items WHERE id = ?", (item_id,))
    connection.commit()
    connection.close()
    return redirect(url_for("view_cart"))

@app.route("/checkout")
def checkout():
    connection = get_db_connection()
    cart = get_or_create_cart(connection)

    items = connection.execute("""
        SELECT cart_items.id, cart_items.quantity,
               products.id as product_id, products.name,
               products.price, products.stock_quantity
        FROM cart_items
        JOIN products ON cart_items.product_id = products.id
        WHERE cart_items.cart_id = ?
    """, (cart["id"],)).fetchall()

    connection.close()

    if len(items) == 0:
        return redirect(url_for("view_cart"))

    total = sum(item["price"] * item["quantity"] for item in items)

    return render_template("checkout.html", items=items, total=total)


@app.route("/place-order", methods=["POST"])
def place_order():
    full_name = request.form.get("full_name")
    phone = request.form.get("phone")
    address = request.form.get("address")

    connection = get_db_connection()
    cart = get_or_create_cart(connection)

    items = connection.execute("""
        SELECT cart_items.id as cart_item_id, cart_items.quantity,
               products.id as product_id, products.name, products.price
        FROM cart_items
        JOIN products ON cart_items.product_id = products.id
        WHERE cart_items.cart_id = ?
    """, (cart["id"],)).fetchall()

    if len(items) == 0:
        connection.close()
        return redirect(url_for("view_cart"))

    order_id = None

    try:
        connection.execute("BEGIN")

        for item in items:
            result = connection.execute(
                "UPDATE products SET stock_quantity = stock_quantity - ? "
                "WHERE id = ? AND stock_quantity >= ?",
                (item["quantity"], item["product_id"], item["quantity"])
            )

            if result.rowcount == 0:
                raise Exception(f"Not enough stock for {item['name']}")

        total = sum(item["price"] * item["quantity"] for item in items)

        cursor = connection.execute(
            "INSERT INTO orders (status, total) VALUES (?, ?)",
            ("confirmed", total)
        )
        order_id = cursor.lastrowid

        for item in items:
            connection.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, price_at_purchase) "
                "VALUES (?, ?, ?, ?)",
                (order_id, item["product_id"], item["quantity"], item["price"])
            )

        connection.execute("DELETE FROM cart_items WHERE cart_id = ?", (cart["id"],))

        connection.commit()

    except Exception as error:
        connection.rollback()

        items_for_display = connection.execute("""
            SELECT cart_items.id, cart_items.quantity,
                   products.id as product_id, products.name,
                   products.price, products.stock_quantity
            FROM cart_items
            JOIN products ON cart_items.product_id = products.id
            WHERE cart_items.cart_id = ?
        """, (cart["id"],)).fetchall()

        connection.close()

        total = sum(i["price"] * i["quantity"] for i in items_for_display)

        return render_template(
            "checkout.html",
            items=items_for_display,
            total=total,
            error=str(error)
        )

    connection.close()
    return redirect(url_for("order_confirmation", order_id=order_id))


@app.route("/order-confirmation/<int:order_id>")
def order_confirmation(order_id):
    connection = get_db_connection()

    order = connection.execute(
        "SELECT * FROM orders WHERE id = ?", (order_id,)
    ).fetchone()

    items = connection.execute("""
        SELECT order_items.quantity, order_items.price_at_purchase,
               products.name
        FROM order_items
        JOIN products ON order_items.product_id = products.id
        WHERE order_items.order_id = ?
    """, (order_id,)).fetchall()

    connection.close()

    return render_template("order_confirmation.html", order=order, items=items)


@app.route("/")
def home():
    connection = get_db_connection()
    featured_product = connection.execute(
        "SELECT * FROM products WHERE name = ?", ("Vintage T9 Clipper",)
    ).fetchone()
    connection.close()
    return render_template("home.html", product=featured_product)


@app.route("/collections")
def collections():
    search_query = request.args.get("search", "")
    sort_option = request.args.get("sort", "")
    category = request.args.get("category", "")

    connection = get_db_connection()

    sql = "SELECT * FROM products WHERE 1=1"
    params = []

    if search_query:
        sql += " AND name LIKE ?"
        params.append("%" + search_query + "%")

    if category:
        sql += " AND category = ?"
        params.append(category)

    if sort_option == "price_low":
        sql += " ORDER BY price ASC"
    elif sort_option == "price_high":
        sql += " ORDER BY price DESC"
    elif sort_option == "stock_low":
        sql += " ORDER BY stock_quantity ASC"
    elif sort_option == "stock_high":
        sql += " ORDER BY stock_quantity DESC"

    products = connection.execute(sql, params).fetchall()
    connection.close()

    return render_template(
        "collections.html",
        products=products,
        search_query=search_query,
        sort_option=sort_option,
        category=category
    )


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/search-suggestions")
def search_suggestions():
    query = request.args.get("q", "")
    connection = get_db_connection()
    results = connection.execute(
        "SELECT id, name, price FROM products WHERE name LIKE ? LIMIT 5",
        ("%" + query + "%",)
    ).fetchall()
    connection.close()

    suggestions = [
        {"id": row["id"], "name": row["name"], "price": row["price"]}
        for row in results
    ]
    return jsonify(suggestions)


if __name__ == "__main__":
    app.run(debug=True, port=5002)
import sqlite3

connection = sqlite3.connect("store.db")

with open("schema.sql") as f:
    connection.executescript(f.read())

cursor = connection.cursor()

cursor.execute("DELETE FROM products")

sample_products = [
    ("Vintage T9 Clipper", 22000, 12, "clippers"),
    ("Pro Cordless Trimmer", 18500, 5, "trimmers"),
    ("Gold Edge Clipper", 25000, 1, "clippers"),
    ("Barber Essentials Kit", 32000, 0, "grooming-kits"),
]

cursor.executemany(
    "INSERT INTO products (name, price, stock_quantity, category) VALUES (?, ?, ?, ?)",
    sample_products
)

connection.commit()
connection.close()

print("Database created and products added.")
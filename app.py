from flask import Flask, render_template, request, redirect, url_for, flash
import qrcode, os, sqlite3

app = Flask(__name__)
app.secret_key = "supersecretkey"  # needed for flash messages
app.config['UPLOAD_FOLDER'] = 'static/qr_codes'

# Ensure qr_codes folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Database setup ---
def init_db():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()

    # Items table
    c.execute('''CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        price REAL NOT NULL,
        qr_code TEXT
    )''')

    # Sales table
    c.execute('''CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id INTEGER,
        quantity INTEGER,
        total REAL,
        date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (item_id) REFERENCES items(id)
    )''')

    conn.commit()
    conn.close()

# Run once at startup
with app.app_context():
    init_db()

# --- Helper: Generate QR code ---
def generate_qr(item_id, name):
    qr_data = f"Item ID: {item_id}, Name: {name}"
    filename = f"{item_id}_{name}.png"
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    img = qrcode.make(qr_data)
    img.save(path)
    return f"qr_codes/{filename}"

# --- Routes ---
@app.route('/')
def index():
    return render_template("index.html", title="Home")

@app.route('/add', methods=['GET', 'POST'])
def add_item():
    if request.method == 'POST':
        name = request.form['name']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])

        conn = sqlite3.connect('inventory.db')
        c = conn.cursor()
        c.execute("INSERT INTO items (name, quantity, price) VALUES (?, ?, ?)",
                  (name, quantity, price))
        item_id = c.lastrowid
        conn.commit()
        conn.close()

        # Generate QR code
        qr_path = generate_qr(item_id, name)

        conn = sqlite3.connect('inventory.db')
        c = conn.cursor()
        c.execute("UPDATE items SET qr_code=? WHERE id=?", (qr_path, item_id))
        conn.commit()
        conn.close()

        flash("✅ Item added successfully!", "success")
        return redirect(url_for('inventory'))

    return render_template("add_item.html", title="Add Item")

@app.route('/inventory')
def inventory():
    search_query = request.args.get('q', '')

    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    if search_query:
        c.execute("SELECT * FROM items WHERE name LIKE ?", ('%' + search_query + '%',))
    else:
        c.execute("SELECT * FROM items")
    items = c.fetchall()
    conn.close()

    formatted_items = [
        {"id": row[0], "name": row[1], "quantity": row[2], "price": row[3], "qr_code": row[4]}
        for row in items
    ]

    return render_template("inventory.html", items=formatted_items, title="Inventory")

@app.route('/edit/<int:item_id>', methods=['GET', 'POST'])
def edit_item(item_id):
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute("SELECT * FROM items WHERE id=?", (item_id,))
    item = c.fetchone()

    if not item:
        return "Item not found", 404

    if request.method == 'POST':
        name = request.form['name']
        quantity = int(request.form['quantity'])
        price = float(request.form['price'])

        c.execute("UPDATE items SET name=?, quantity=?, price=? WHERE id=?",
                  (name, quantity, price, item_id))
        conn.commit()
        conn.close()

        flash("✏️ Item updated successfully!", "info")
        return redirect(url_for('inventory'))

    conn.close()
    return render_template("add_item.html", title="Edit Item", item=item)

@app.route('/delete/<int:item_id>', methods=['POST'])
def delete_item(item_id):
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute("DELETE FROM items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()

    flash("🗑️ Item deleted!", "danger")
    return redirect(url_for('inventory'))

@app.route('/sell/<int:item_id>', methods=['GET', 'POST'])
def sell(item_id):
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute("SELECT * FROM items WHERE id=?", (item_id,))
    item = c.fetchone()

    if not item:
        conn.close()
        return "Item not found", 404

    if request.method == 'POST':
        qty_sold = int(request.form['quantity'])

        if qty_sold > item[2]:  # stock check
            conn.close()
            flash("❌ Not enough stock!", "danger")
            return redirect(url_for('inventory'))

        new_qty = item[2] - qty_sold
        total_price = qty_sold * item[3]

        # Update stock
        c.execute("UPDATE items SET quantity=? WHERE id=?", (new_qty, item_id))

        # Record sale
        c.execute("INSERT INTO sales (item_id, quantity, total) VALUES (?, ?, ?)",
                  (item_id, qty_sold, total_price))

        conn.commit()
        conn.close()

        flash(f"💰 Sold {qty_sold} of {item[1]} for ₦{total_price}", "success")
        return redirect(url_for('sales'))

    conn.close()
    return render_template("sell_item.html", item=item, title="Sell Item")

@app.route('/sales')
def sales():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()
    c.execute('''SELECT sales.id, items.name, sales.quantity, sales.total, sales.date
                 FROM sales JOIN items ON sales.item_id = items.id
                 ORDER BY sales.date DESC''')
    sales_data = c.fetchall()
    conn.close()

    return render_template("sales.html", sales=sales_data, title="Sales History")

@app.route('/dashboard')
def dashboard():
    conn = sqlite3.connect('inventory.db')
    c = conn.cursor()

    # Sales trend (monthly sums)
    c.execute("SELECT strftime('%m', date), SUM(total) FROM sales GROUP BY strftime('%m', date)")
    sales = c.fetchall()
    sales_labels = [f"Month {row[0]}" for row in sales]
    sales_data = [row[1] for row in sales]

    # Top-selling items
    c.execute("SELECT items.name, SUM(sales.quantity) FROM sales JOIN items ON sales.item_id = items.id GROUP BY items.name ORDER BY SUM(sales.quantity) DESC LIMIT 5")
    top_items = c.fetchall()
    top_items_labels = [row[0] for row in top_items]
    top_items_data = [row[1] for row in top_items]

    # Low stock alerts
    c.execute("SELECT name, quantity FROM items WHERE quantity <= 5")
    low_stock = c.fetchall()
    low_stock_labels = [row[0] for row in low_stock]
    low_stock_data = [row[1] for row in low_stock]

    conn.close()

    return render_template(
        "dashboard.html",
        sales_labels=sales_labels,
        sales_data=sales_data,
        top_items_labels=top_items_labels,
        top_items_data=top_items_data,
        low_stock_labels=low_stock_labels,
        low_stock_data=low_stock_data
    )

# --- Export Placeholders ---
@app.route("/export/pdf")
def export_pdf():
    return "📄 PDF export coming soon!"

@app.route("/export/excel")
def export_excel():
    return "📊 Excel export coming soon!"

if __name__ == "__main__":
    app.run(debug=True)

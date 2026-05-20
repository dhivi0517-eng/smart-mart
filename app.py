from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
from flask_mail import Mail, Message
import random
import datetime
from dotenv import load_dotenv

load_dotenv()
from models import db, User, Shop, Product, Order, OrderItem, ShopRating, ProductRating
from recommender import recommender
from chatbot import bot as chatbot

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'multistore_secret')

# ==========================================
# DATABASE & ENVIRONMENT CONFIGURATION
# ==========================================
# 1. Supabase PostgreSQL Integration:
# - Locally: Create a '.env' file in the root directory (based on .env.example) and add your connection string.
#   Example: DATABASE_URL=postgresql://postgres.xxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
# - For Vercel Deployment: Go to your project settings in the Vercel Dashboard, navigate to "Environment Variables",
#   and add the DATABASE_URL key with your Supabase Connection String.
# - How Environment Variables Work: python-dotenv loads the local .env variables during development.
#   In production, Vercel injects the environment variables securely into os.environ.

database_url = os.environ.get("DATABASE_URL")

# SQLAlchemy requires postgresql:// instead of postgres:// for PostgreSQL URIs
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# ==========================================
# FILE UPLOADS CONFIGURATION FOR SERVERLESS
# ==========================================
# Serverless platforms like Vercel have a read-only filesystem, except for the '/tmp' directory.
# This configuration dynamically assigns the upload directory to '/tmp/uploads' on Vercel
# to prevent "ReadOnlyFileSystem" 500 errors when users upload product images.
if os.environ.get('VERCEL') == '1':
    app.config['UPLOAD_FOLDER'] = '/tmp/uploads'
else:
    app.config['UPLOAD_FOLDER'] = 'static/uploads'

# Ensure the upload directory is automatically created
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Mail Configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

db.init_app(app)
mail = Mail(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"






from reportlab.pdfgen import canvas

@app.route('/invoice/<int:order_id>')
def invoice(order_id):
    order = Order.query.get(order_id)

    file = f"invoice_{order.id}.pdf"
    c = canvas.Canvas(file)

    c.drawString(100, 750, f"Order ID: {order.id}")
    c.drawString(100, 720, f"Total: ₹{order.total}")

    c.save()
    return send_file(file, as_attachment=True)

@app.route('/profile')
@login_required
def profile():
    return render_template("profile.html")

@app.route('/search')
@login_required
def search():

    query = request.args.get('q')

    products = Product.query.filter(
        Product.name.contains(query)
    ).all()

    return render_template(
        "shop_products.html",
        products=products,
        shop=None
    )

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        return redirect(url_for('index'))

    users = User.query.all()
    shops = Shop.query.all()
    orders = Order.query.all()

    return render_template("admin_dashboard.html", users=users, shops=shops, orders=orders)





@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ================= HOME =================
@app.route('/')
def index():
    return render_template("index.html")


# ================= REGISTER =================
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role')

            if not email or not username or not password or not role:
                flash("Missing required fields ❌")
                return redirect(url_for('register'))

            if User.query.filter_by(email=email).first():
                flash("Email already exists ❌")
                return redirect(url_for('register'))

            hashed_password = generate_password_hash(password)

            # Generate OTP
            otp = str(random.randint(100000, 999999))
            otp_expiry = datetime.datetime.now() + datetime.timedelta(minutes=10)

            user = User(
                username=username,
                email=email,
                password=hashed_password,
                role=role,
                otp=otp,
                otp_expiry=otp_expiry
            )

            db.session.add(user)
            db.session.commit()

            if user.role == "owner":
                shop_name = request.form.get('shop_name')
                shop_address = request.form.get('shop_address')
                
                shop = Shop(
                    name=shop_name or "My Shop",
                    address=shop_address or "",
                    owner_id=user.id
                )
                db.session.add(shop)
                db.session.commit()

            # Send OTP via Email
            try:
                msg = Message("Verify Your Email - MiniMartPro", recipients=[user.email])
                msg.body = f"Hello {user.username},\n\nYour OTP for email verification is: {otp}\nIt is valid for 10 minutes.\n\nThank you,\nMiniMartPro Team"
                mail.send(msg)
                flash("OTP sent to your email. Please verify ✅")
            except Exception as mail_err:
                print("ERROR: Mail delivery failed:", str(mail_err))
                flash("Registered successfully, but failed to send verification email. ❌")

            return redirect(url_for('verify_email', email=user.email))
        except Exception as e:
            db.session.rollback()
            print("ERROR: Registration failed:", str(e))
            flash(f"Registration failed: {e} ❌")
            return redirect(url_for('register'))

    return render_template("register.html")


# ================= VERIFY EMAIL =================
@app.route('/verify_email', methods=['GET', 'POST'])
def verify_email():
    email = request.args.get('email')
    if not email:
        return redirect(url_for('register'))

    if request.method == 'POST':
        try:
            otp_input = request.form.get('otp')
            user = User.query.filter_by(email=email).first()

            if not user:
                flash("User not found ❌")
                return redirect(url_for('register'))

            if user.is_verified:
                flash("Already verified ✅")
                return redirect(url_for('login'))

            if user.otp == otp_input and user.otp_expiry and user.otp_expiry > datetime.datetime.now():
                user.is_verified = True
                user.otp = None
                user.otp_expiry = None
                db.session.commit()
                flash("Email verified successfully! You can now log in ✅")
                return redirect(url_for('login'))
            else:
                flash("Invalid or expired OTP ❌")
        except Exception as e:
            db.session.rollback()
            print("ERROR: Email verification failed:", str(e))
            flash(f"Verification error: {e} ❌")

    return render_template("verify_email.html", email=email)


# ================= LOGIN =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            email = request.form.get('email')
            password = request.form.get('password')

            if not email or not password:
                flash("Missing email or password ❌")
                return redirect(url_for('login'))

            user = User.query.filter_by(email=email).first()

            if not user:
                flash("User not found ❌")
                return redirect(url_for('login'))

            if not check_password_hash(user.password, password):
                flash("Wrong password ❌")
                return redirect(url_for('login'))

            if not user.is_verified:
                flash("Please verify your email first ❌")
                return redirect(url_for('verify_email', email=user.email))

            login_success = login_user(user)
            if not login_success:
                print("ERROR: Flask-Login login_user returned False")
                flash("Unable to sign in. Please verify your account is active. ❌")
                return redirect(url_for('login'))

            if user.role == "owner":
                return redirect(url_for('owner_dashboard'))

            return redirect(url_for('shop_list'))
        except Exception as e:
            print("ERROR: Login failed:", str(e))
            flash(f"Login failed: {e} ❌")
            return redirect(url_for('login'))

    return render_template("login.html")


# ================= LOGOUT =================
@app.route('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('index'))


# ================= SHOP LIST =================
@app.route('/shops')
@login_required
def shop_list():
    query = request.args.get('q')
    if query:
        shops = Shop.query.filter(Shop.name.contains(query)).all()
    else:
        shops = Shop.query.all()
    return render_template("shop_list.html", shops=shops, search_query=query)


# ================= SHOP PRODUCTS =================
@app.route('/shop/<int:shop_id>')
@login_required
def shop_products(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    products = Product.query.filter_by(shop_id=shop.id).all()
    
    try:
        recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, limit=4)
    except:
        recommendations = []
        
    return render_template("shop_products.html", shop=shop, products=products, recommendations=recommendations)


# ================= OWNER DASHBOARD =================
@app.route('/owner')
@login_required
def owner_dashboard():
    if current_user.role != "owner":
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Shop not found. Please register a shop.")
        return redirect(url_for('index'))

    products = Product.query.filter_by(shop_id=shop.id).all()

    orders = Order.query.filter_by(shop_id=shop.id)\
                        .order_by(Order.id.desc())\
                        .all()

    return render_template("owner_dashboard.html",
                           shop=shop,
                           products=products,
                           orders=orders)


# ================= CUSTOMER ORDER HISTORY =================
@app.route('/my_orders')
@login_required
def my_orders():
    if current_user.role != "customer":
        return redirect(url_for('index'))

    orders = Order.query.filter_by(customer_id=current_user.id)\
                        .order_by(Order.id.desc())\
                        .all()

    try:
        recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, limit=4)
    except:
        recommendations = []

    return render_template("orders.html", orders=orders, recommendations=recommendations)


# ================= ADD PRODUCT =================
@app.route('/add_product', methods=['GET', 'POST'])
@login_required
def add_product():
    if current_user.role != "owner":
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Shop not found. Please setup a shop first.")
        return redirect(url_for('index'))

    if request.method == 'POST':

        image = request.files.get('image')
        filename = None

        if image and image.filename != "":
            filename = secure_filename(image.filename)
            upload_path = os.path.join(app.root_path, 'static', 'uploads')
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)
            image.save(os.path.join(upload_path, filename))

        try:
            product = Product(
                name=request.form['name'],
                description=request.form['description'],
                price=float(request.form['price']),
                stock=float(request.form['stock']),
                image=filename,
                shop_id=shop.id
            )
            db.session.add(product)
            db.session.commit()
            flash("Product Added Successfully")
        except Exception as e:
            db.session.rollback()
            flash("Error adding product. Please check your inputs.")

        return redirect(url_for('owner_dashboard'))

    return render_template("add_product.html")


# ================= ADD TO CART =================
@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    quantity = float(request.form['quantity'])

    if quantity <= 0:
        return redirect(request.referrer)

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']
    cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
    session['cart'] = cart

    flash("Added to Cart")
    return redirect(request.referrer)


# ================= CART =================
@app.route('/cart')
@login_required
def cart():
    cart = session.get('cart', {})
    items = []
    total = 0
    cart_product_ids = []

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))
        if not product:
            continue

        cart_product_ids.append(int(pid))
        subtotal = product.price * qty
        total += subtotal

        items.append({
            'product': product,
            'quantity': qty,
            'subtotal': subtotal
        })

    try:
        recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, cart_product_ids=cart_product_ids, limit=4)
    except Exception as e:
        print(f"Error getting recommendations: {e}")
        recommendations = []

    return render_template("cart.html", items=items, total=total, recommendations=recommendations)

@app.route('/owner_orders')
@login_required
def owner_orders():
    if current_user.role != "owner":
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    orders = Order.query.filter_by(shop_id=shop.id).order_by(Order.id.desc()).all()

    return render_template("owner_orders.html", orders=orders)

# ================= PLACE ORDER =================
@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    cart = session.get('cart', {})

    if not cart:
        flash("Cart is empty")
        return redirect(url_for('shop_list'))

    payment_method = request.form['payment']

    first_product = Product.query.get(int(list(cart.keys())[0]))
    shop_id = first_product.shop_id

    order = Order(
        customer_id=current_user.id,
        shop_id=shop_id,
        total=0,
        payment_method=payment_method,
        status="Pending"
    )
    db.session.add(order)
    db.session.commit()

    total = 0

    for pid, qty in cart.items():
        product = Product.query.get(int(pid))

        if product.stock < qty:
            flash(f"Not enough stock for {product.name}")
            return redirect(url_for('cart'))

        subtotal = product.price * qty
        total += subtotal

        # Reduce stock
        product.stock -= qty

        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=qty
        )
        db.session.add(item)

    order.total = total
    db.session.commit()

    session.pop('cart', None)

    # Retrain recommender async or synchronously to reflect new order
    try:
        recommender.train_models()
    except:
        pass

    flash("Order Placed Successfully")
    return redirect(url_for('my_orders'))


# ================= UPDATE STATUS =================
@app.route('/update_status/<int:order_id>')
@login_required
def update_status(order_id):
    order = Order.query.get(order_id)

    if order.status == "Pending":
        order.status = "Accepted"
    elif order.status == "Accepted":
        order.status = "Ready"
    elif order.status == "Ready":
        order.status = "Completed"

    db.session.commit()
    return redirect(request.referrer)

@app.route('/analytics')
@login_required
def analytics():
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    orders = Order.query.filter_by(shop_id=shop.id).all()

    total_orders = len(orders)
    revenue = sum(o.total for o in orders)

    return render_template("analytics.html", total_orders=total_orders, revenue=revenue)


# ================= RATING =================
@app.route('/rate_shop/<int:shop_id>', methods=['POST'])
@login_required
def rate_shop(shop_id):
    if current_user.role != 'customer':
        flash("Only customers can rate shops.")
        return redirect(request.referrer)
    
    rating_val = int(request.form.get('rating', 0))
    if rating_val < 1 or rating_val > 5:
        flash("Invalid rating.")
        return redirect(request.referrer)
        
    rating = ShopRating.query.filter_by(shop_id=shop_id, user_id=current_user.id).first()
    if rating:
        rating.rating = rating_val
    else:
        rating = ShopRating(shop_id=shop_id, user_id=current_user.id, rating=rating_val)
        db.session.add(rating)
        
    db.session.commit()
    flash("Shop rated successfully!")
    return redirect(request.referrer)

@app.route('/rate_product/<int:product_id>', methods=['POST'])
@login_required
def rate_product(product_id):
    if current_user.role != 'customer':
        flash("Only customers can rate products.")
        return redirect(request.referrer)
        
    rating_val = int(request.form.get('rating', 0))
    if rating_val < 1 or rating_val > 5:
        flash("Invalid rating.")
        return redirect(request.referrer)
        
    rating = ProductRating.query.filter_by(product_id=product_id, user_id=current_user.id).first()
    if rating:
        rating.rating = rating_val
    else:
        rating = ProductRating(product_id=product_id, user_id=current_user.id, rating=rating_val)
        db.session.add(rating)
        
    db.session.commit()
    flash("Product rated successfully!")
    return redirect(request.referrer)

# ================= CHATBOT =================
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json()
    message = data.get('message', '')
    
    response = chatbot.process_message(message)
    
    if response.get("action") == "add_to_cart":
        product_id = response.get("product_id")
        quantity = response.get("quantity")
        
        if 'cart' not in session:
            session['cart'] = {}
            
        cart = session['cart']
        cart[str(product_id)] = cart.get(str(product_id), 0) + quantity
        session['cart'] = cart
        session.modified = True
        
    return jsonify(response)

# ================= INIT =================
def check_and_update_db_schema():
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        return
    try:
        from sqlalchemy import text
        if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
            with db.engine.begin() as conn:
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;'))
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS otp VARCHAR(6);'))
                conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS otp_expiry TIMESTAMP;'))
                print("PostgreSQL database columns verified/created successfully.")
    except Exception as e:
        print("ERROR: PostgreSQL schema check/update failed:", str(e))

with app.app_context():
    if app.config.get('SQLALCHEMY_DATABASE_URI'):
        try:
            db.create_all()
            check_and_update_db_schema()
            recommender.train_models()
            print("Database initialized and ML Recommender models trained successfully.")
        except Exception as e:
            print("ERROR: Database initialization failed:", str(e))
    else:
        print("Warning: SQLALCHEMY_DATABASE_URI is not set. Database initialization skipped.")

# Vercel requires app to be exported, which it is.
# app.run should only execute locally.
if __name__ == "__main__":
    # If not on Vercel, run locally
    if os.environ.get('VERCEL') != '1':
        app.run(debug=True)
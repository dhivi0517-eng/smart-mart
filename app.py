from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, jsonify, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import io
from functools import wraps
from flask_mail import Mail, Message
import random
import datetime
from dotenv import load_dotenv

load_dotenv()
from models import db, User, Shop, Product, Order, OrderItem, ShopRating, ProductRating, ShopConnection, ShopPost, ShopOffer, ProfileCustomization, Wishlist, ShopLocation, ShopVerification, PaymentMethods, UPIPayments, GPSLogs, Notification, Analytics
from recommender import recommender
from chatbot import bot as chatbot

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'multistore_secret')

# ==========================================
# SUPER ADMIN SECURITY DECORATORS & CONTEXT
# ==========================================
def super_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        super_admin_email = os.environ.get("SUPER_ADMIN_EMAIL")
        if not super_admin_email or current_user.email != super_admin_email:
            flash("Access Denied: Super Admin permissions required! ❌")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_super_admin_check():
    super_admin_email = os.environ.get("SUPER_ADMIN_EMAIL")
    def is_super_admin():
        if not current_user.is_authenticated:
            return False
        return super_admin_email and current_user.email == super_admin_email
    return dict(is_super_admin=is_super_admin, super_admin_email=super_admin_email)

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        # Retrieve user notifications + system broadcast (user_id is None)
        notifs = Notification.query.filter(
            (Notification.user_id == current_user.id) | (Notification.user_id == None)
        ).order_by(Notification.created_at.desc()).limit(8).all()
        unread_count = sum(1 for n in notifs if not n.is_read)
        return dict(user_notifications=notifs, unread_notifications_count=unread_count)
    return dict(user_notifications=[], unread_notifications_count=0)

# ==========================================
# QUANTITY & UNIT UTILITIES
# ==========================================
def convert_to_price_unit(quantity, unit, price_unit):
    try:
        qty = float(quantity)
    except (ValueError, TypeError):
        qty = 1.0
        
    if price_unit in ['kg', 'g', '100g', '250g', '500g']:
        if unit == 'kg':
            grams = qty * 1000
        else:
            grams = qty
            
        if price_unit == 'kg':
            return grams / 1000
        elif price_unit == 'g':
            return grams
        elif price_unit == '100g':
            return grams / 100
        elif price_unit == '250g':
            return grams / 250
        elif price_unit == '500g':
            return grams / 500
    
    return qty

def format_display_quantity(quantity, price_unit):
    if quantity is None:
        return ""
    try:
        qty = float(quantity)
    except (ValueError, TypeError):
        return str(quantity)
        
    if price_unit == 'kg':
        if qty < 1.0:
            return f"{int(qty * 1000)} g"
        else:
            if qty.is_integer():
                return f"{int(qty)} kg"
            return f"{qty} kg"
    elif price_unit == 'g':
        if qty.is_integer():
            return f"{int(qty)} g"
        return f"{qty} g"
    elif price_unit == '100g':
        val = qty * 100
        if val.is_integer():
            return f"{int(val)} g"
        return f"{val} g"
    elif price_unit == '250g':
        val = qty * 250
        if val.is_integer():
            return f"{int(val)} g"
        return f"{val} g"
    elif price_unit == '500g':
        val = qty * 500
        if val.is_integer():
            return f"{int(val)} g"
        return f"{val} g"
    elif price_unit == 'piece':
        if qty.is_integer():
            return f"{int(qty)} piece{'s' if qty != 1 else ''}"
        return f"{qty} piece{'s' if qty != 1 else ''}"
    else:
        if qty.is_integer():
            return f"{int(qty)} {price_unit}"
        return f"{qty} {price_unit}"

app.jinja_env.filters['format_quantity'] = format_display_quantity

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

# Custom route to serve uploaded files seamlessly from /tmp/uploads on Vercel or static/uploads locally
@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


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
@login_required
def invoice(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found ❌")
        return redirect(url_for('index'))

    # Authorization check
    if current_user.role == 'customer' and order.customer_id != current_user.id:
        flash("Unauthorized access ❌")
        return redirect(url_for('my_orders'))
    elif current_user.role == 'owner':
        shop = Shop.query.filter_by(owner_id=current_user.id).first()
        if not shop or order.shop_id != shop.id:
            flash("Unauthorized access ❌")
            return redirect(url_for('owner_dashboard'))
    elif current_user.role not in ['customer', 'owner', 'admin']:
        flash("Unauthorized access ❌")
        return redirect(url_for('index'))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)

    c.drawString(100, 750, f"Order ID: {order.id}")
    c.drawString(100, 720, f"Total: INR {order.total}")

    c.save()
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"invoice_{order.id}.pdf",
        mimetype='application/pdf'
    )

@app.route('/profile')
@login_required
def profile():
    customization = ProfileCustomization.query.filter_by(user_id=current_user.id).first()
    if not customization:
        customization = ProfileCustomization(user_id=current_user.id)
        db.session.add(customization)
        db.session.commit()

    # Dynamic Profile Completion Percentage Calculator
    fields = [customization.bio, customization.location, customization.phone, customization.profile_photo, customization.cover_image]
    socials = [customization.instagram_link, customization.facebook_link, customization.twitter_link, customization.website_link]
    
    filled = sum(1 for f in fields if f)
    social_filled = sum(1 for s in socials if s)
    if social_filled > 0:
        filled += 1
    total_fields = len(fields) + 1 # 5 fields + 1 generic socials group

    shop = None
    if current_user.role == 'owner':
        shop = Shop.query.filter_by(owner_id=current_user.id).first()
        if shop:
            shop_fields = [shop.logo, shop.banner_image, shop.bio, shop.category]
            filled += sum(1 for sf in shop_fields if sf)
            total_fields += len(shop_fields)

    completion_percentage = int((filled / total_fields) * 100)

    if current_user.role == 'customer':
        # Connected shops
        connections = ShopConnection.query.filter_by(customer_id=current_user.id).all()
        connected_shop_ids = [c.shop_id for c in connections]
        connected_shops = Shop.query.filter(Shop.id.in_(connected_shop_ids)).all() if connected_shop_ids else []

        # Connected shops feed: Unified list of Posts and Offers
        feed_items = []
        if connected_shop_ids:
            posts = ShopPost.query.filter(ShopPost.shop_id.in_(connected_shop_ids)).all()
            offers = ShopOffer.query.filter(ShopOffer.shop_id.in_(connected_shop_ids)).all()
            
            for p in posts:
                feed_items.append({
                    'type': 'post',
                    'item': p,
                    'created_at': p.created_at,
                    'shop': p.shop
                })
            for o in offers:
                feed_items.append({
                    'type': 'offer',
                    'item': o,
                    'created_at': o.created_at,
                    'shop': o.shop
                })
            # Sort feed by newest first
            feed_items.sort(key=lambda x: x['created_at'], reverse=True)

        # Recommendations (shops that the customer is not connected to yet)
        recommended_shops = Shop.query.filter(~Shop.id.in_(connected_shop_ids)).limit(4).all() if connected_shop_ids else Shop.query.limit(4).all()

        # Customer Stats
        total_orders = len(current_user.orders)
        recent_orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.id.desc()).limit(3).all()

        # Fetch actual Wishlisted products
        wishlist_records = Wishlist.query.filter_by(user_id=current_user.id).all()
        wishlisted_products = [w.product for w in wishlist_records]

        try:
            recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, limit=8)
            try:
                log_event = Analytics(
                    event_type='recommender_use',
                    user_id=current_user.id,
                    details=f"Generated {len(recommendations)} recommendations for profile view"
                )
                db.session.add(log_event)
                db.session.commit()
            except Exception as analytics_err:
                db.session.rollback()
                print("[DEBUG LOG] Recommender analytics log failed:", analytics_err)
        except:
            recommendations = []

        return render_template(
            "profile.html",
            customization=customization,
            connected_shops=connected_shops,
            feed_items=feed_items[:15], # Limit to latest 15 feed items
            recommended_shops=recommended_shops,
            total_orders=total_orders,
            recent_orders=recent_orders,
            recommendations=recommendations,
            completion_percentage=completion_percentage,
            wishlisted_products=wishlisted_products
        )

    else: # Owner
        if not shop:
            flash("Please setup your shop! ❌")
            return redirect(url_for('index'))

        # Stats
        products_count = Product.query.filter_by(shop_id=shop.id).count()
        connections_count = ShopConnection.query.filter_by(shop_id=shop.id).count()
        
        orders = Order.query.filter_by(shop_id=shop.id).all()
        revenue = sum(o.total for o in orders)
        recent_orders = Order.query.filter_by(shop_id=shop.id).order_by(Order.id.desc()).limit(5).all()

        # Offers & Posts
        offers = ShopOffer.query.filter_by(shop_id=shop.id).order_by(ShopOffer.id.desc()).all()
        posts = ShopPost.query.filter_by(shop_id=shop.id).order_by(ShopPost.id.desc()).all()

        return render_template(
            "profile.html",
            customization=customization,
            shop=shop,
            products_count=products_count,
            connections_count=connections_count,
            revenue=revenue,
            recent_orders=recent_orders,
            offers=offers,
            posts=posts,
            completion_percentage=completion_percentage,
            total_orders_count=len(orders)
        )

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def profile_edit():
    customization = ProfileCustomization.query.filter_by(user_id=current_user.id).first()
    if not customization:
        customization = ProfileCustomization(user_id=current_user.id)
        db.session.add(customization)
        db.session.commit()

    shop = None
    if current_user.role == "owner":
        shop = Shop.query.filter_by(owner_id=current_user.id).first()

    if request.method == 'POST':
        customization.bio = request.form.get('bio')
        customization.location = request.form.get('location')
        customization.phone = request.form.get('phone')
        customization.instagram_link = request.form.get('instagram')
        customization.facebook_link = request.form.get('facebook')
        customization.twitter_link = request.form.get('twitter')
        customization.website_link = request.form.get('website')

        # Handling File Uploads
        profile_photo = request.files.get('profile_photo')
        if profile_photo and profile_photo.filename != "":
            filename = secure_filename(profile_photo.filename)
            filename = f"avatar_{current_user.id}_{filename}"
            profile_photo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            customization.profile_photo = filename

        cover_image = request.files.get('cover_image')
        if cover_image and cover_image.filename != "":
            filename = secure_filename(cover_image.filename)
            filename = f"cover_{current_user.id}_{filename}"
            cover_image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            customization.cover_image = filename

        if current_user.role == "owner" and shop:
            shop.category = request.form.get('shop_category', 'General')
            shop.bio = request.form.get('shop_bio')
            
            shop_logo = request.files.get('shop_logo')
            if shop_logo and shop_logo.filename != "":
                filename = secure_filename(shop_logo.filename)
                filename = f"logo_{shop.id}_{filename}"
                shop_logo.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                shop.logo = filename
            
            shop_banner = request.files.get('shop_banner')
            if shop_banner and shop_banner.filename != "":
                filename = secure_filename(shop_banner.filename)
                filename = f"sbanner_{shop.id}_{filename}"
                shop_banner.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                shop.banner_image = filename

        db.session.commit()
        flash("Profile Updated Successfully! ✅")
        return redirect(url_for('profile'))

    return render_template("profile_edit.html", customization=customization, shop=shop)

# ==========================================
# SHOP VERIFICATION & LOCATION ROUTES
# ==========================================
@app.route('/owner/verification', methods=['GET'])
@login_required
def owner_verification():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Setup your store first! 🏪")
        return redirect(url_for('owner_dashboard'))

    verification = ShopVerification.query.filter_by(shop_id=shop.id).first()
    location = ShopLocation.query.filter_by(shop_id=shop.id).first()

    return render_template(
        "verification.html", 
        shop=shop, 
        verification=verification, 
        location=location,
        status=shop.verification_status
    )

@app.route('/owner/verification/submit', methods=['POST'])
@login_required
def owner_verification_submit():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Setup your store first! 🏪")
        return redirect(url_for('owner_dashboard'))

    # Ensure uploads folder is created automatically
    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    except Exception as e:
        print(f"[DEBUG LOG] Failed to create upload folder: {e}")

    phone_number = request.form.get('phone_number')
    gst_number = request.form.get('gst_number')
    latitude = request.form.get('latitude')
    longitude = request.form.get('longitude')
    map_address = request.form.get('map_address')

    try:
        lat = float(latitude) if latitude else 13.0827
        lng = float(longitude) if longitude else 80.2707
    except ValueError:
        flash("Invalid lat/lng coordinates entered ❌")
        return redirect(url_for('owner_verification'))

    # Retrieve or create verification record
    verification = ShopVerification.query.filter_by(shop_id=shop.id).first()
    is_new_verification = False
    if not verification:
        is_new_verification = True
        verification = ShopVerification(
            shop_id=shop.id, 
            phone_number=phone_number,
            front_image="",
            inside_image="",
            business_proof="",
            owner_photo="",
            shop_photo=""
        )
        db.session.add(verification)

    # Required files validation list
    required_keys = ['front_image', 'inside_image', 'owner_photo', 'shop_photo']
    all_keys = ['front_image', 'inside_image', 'owner_photo', 'shop_photo', 'business_proof']
    allowed_extensions = {'png', 'jpg', 'jpeg', 'webp'}

    # 1. Validation for missing required files
    for key in required_keys:
        f = request.files.get(key)
        existing_val = getattr(verification, key, None)
        # Missing if no file is uploaded (or filename is empty) AND no existing filename is recorded
        if (not f or f.filename == "") and not existing_val:
            flash(f"Required verification image missing: {key.replace('_', ' ').title()} ❌")
            if is_new_verification:
                db.session.rollback()
            return redirect(url_for('owner_verification'))

    # 2. Process and save uploaded images
    try:
        import uuid
        for file_key in all_keys:
            f = request.files.get(file_key)
            if f and f.filename != "":
                # Validate case-insensitive extension
                ext = f.filename.split('.')[-1].lower() if '.' in f.filename else ''
                if ext not in allowed_extensions:
                    flash(f"Invalid file extension for {file_key.replace('_', ' ').title()}. Only PNG, JPG, JPEG, and WebP are allowed! ❌")
                    if is_new_verification:
                        db.session.rollback()
                    return redirect(url_for('owner_verification'))
                
                # Generate unique filename to prevent conflict
                safe_name = secure_filename(f.filename)
                unique_prefix = uuid.uuid4().hex[:8]
                filename = f"verify_{shop.id}_{file_key}_{unique_prefix}_{safe_name}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Save file safely
                f.save(save_path)
                print(f"[DEBUG LOG] Successfully saved uploaded file for {file_key}: filename={filename}, path={save_path}")
                
                setattr(verification, file_key, filename)
            else:
                # If file was not uploaded, keep the old value if it exists, or set an empty string (to satisfy NOT NULL)
                existing_val = getattr(verification, file_key, None)
                if not existing_val:
                    setattr(verification, file_key, "")
                    print(f"[DEBUG LOG] No upload for {file_key}; defaulted to empty string.")
                else:
                    print(f"[DEBUG LOG] Preserved existing file for {file_key}: {existing_val}")

        # Update other fields
        verification.phone_number = phone_number
        verification.gst_number = gst_number
        verification.status = "Under Review"
        verification.verification_status = "Under Review"
        verification.latitude = lat
        verification.longitude = lng
        verification.location_link = map_address

        # Save coordinate location records
        location = ShopLocation.query.filter_by(shop_id=shop.id).first()
        if not location:
            location = ShopLocation(shop_id=shop.id, latitude=lat, longitude=lng)
            db.session.add(location)

        location.latitude = lat
        location.longitude = lng
        location.map_address = map_address

        # Commit everything safely
        db.session.commit()
        print(f"[DEBUG LOG] Database insert/update succeeded for Shop ID: {shop.id}")
        flash("Verification credentials submitted successfully! Under active review. ⏱️")
        return redirect(url_for('profile'))

    except Exception as e:
        db.session.rollback()
        print(f"[DEBUG LOG] Database insert/update or file saving failed: {str(e)}")
        flash("An internal server error occurred while processing your verification request. Please try again! ❌")
        return redirect(url_for('owner_verification'))


# ==========================================
# OWNER PAYMENT SETTINGS ROUTE
# ==========================================
@app.route('/owner/payment_settings', methods=['GET'])
@login_required
def owner_payment_settings():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Setup your store first! 🏪")
        return redirect(url_for('owner_dashboard'))

    payment = PaymentMethods.query.filter_by(shop_id=shop.id).first()
    return render_template("payment_settings.html", shop=shop, payment=payment)

@app.route('/owner/payment_settings/submit', methods=['POST'])
@login_required
def owner_payment_settings_submit():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Setup your store first! 🏪")
        return redirect(url_for('owner_dashboard'))

    upi_id = request.form.get('upi_id')
    bank_details = request.form.get('bank_details')
    gpay = request.form.get('gpay') == 'y'
    phonepe = request.form.get('phonepe') == 'y'
    paytm = request.form.get('paytm') == 'y'
    cod = request.form.get('cod') == 'y'

    payment = PaymentMethods.query.filter_by(shop_id=shop.id).first()
    if not payment:
        payment = PaymentMethods(shop_id=shop.id)
        db.session.add(payment)

    payment.upi_id = upi_id
    payment.bank_details = bank_details
    payment.gpay = gpay
    payment.phonepe = phonepe
    payment.paytm = paytm
    payment.cod = cod
    payment.cod_enabled = cod
    payment.gpay_number = upi_id if gpay else ""
    payment.phonepe_number = upi_id if phonepe else ""
    payment.paytm_number = upi_id if paytm else ""

    qr_image = request.files.get('qr_image')
    if qr_image and qr_image.filename != "":
        filename = secure_filename(qr_image.filename)
        filename = f"qr_{shop.id}_{filename}"
        qr_image.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        payment.qr_image = filename

    db.session.commit()
    flash("Checkout Payment Settings updated successfully! 💳")
    return redirect(url_for('profile'))

@app.route('/wishlist/toggle/<int:product_id>', methods=['POST', 'GET'])
@login_required
def toggle_wishlist(product_id):
    if current_user.role != 'customer':
        flash("Only customers can wishlist products! ❌")
        return redirect(request.referrer or url_for('shop_list'))

    product = Product.query.get_or_404(product_id)
    wish = Wishlist.query.filter_by(user_id=current_user.id, product_id=product.id).first()

    if wish:
        db.session.delete(wish)
        db.session.commit()
        flash(f"Removed '{product.name}' from your wishlist 💔")
    else:
        new_wish = Wishlist(user_id=current_user.id, product_id=product.id)
        db.session.add(new_wish)
        db.session.commit()
        flash(f"Added '{product.name}' to your wishlist! 💖")

    return redirect(request.referrer or url_for('product_details', product_id=product.id))

@app.route('/shop/<int:shop_id>/connect', methods=['POST', 'GET'])
@login_required
def toggle_connect(shop_id):
    if current_user.role != 'customer':
        flash("Only customers can connect with shops! ❌")
        return redirect(request.referrer or url_for('shop_list'))

    shop = Shop.query.get_or_404(shop_id)
    conn = ShopConnection.query.filter_by(customer_id=current_user.id, shop_id=shop.id).first()

    if conn:
        db.session.delete(conn)
        db.session.commit()
        flash(f"Disconnected from {shop.name} 💔")
    else:
        new_conn = ShopConnection(customer_id=current_user.id, shop_id=shop.id)
        db.session.add(new_conn)
        db.session.commit()
        flash(f"Connected to {shop.name}! 🤝")

    return redirect(request.referrer or url_for('shop_products', shop_id=shop.id))

@app.route('/owner/post/create', methods=['POST'])
@login_required
def create_post():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Please create a shop first! ❌")
        return redirect(url_for('owner_dashboard'))

    title = request.form.get('title')
    content = request.form.get('content')
    image_file = request.files.get('image')

    if not title or not content:
        flash("Title and Content are required! ❌")
        return redirect(url_for('profile'))

    filename = None
    if image_file and image_file.filename != "":
        filename = secure_filename(image_file.filename)
        filename = f"post_{shop.id}_{int(datetime.datetime.now().timestamp())}_{filename}"
        image_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

    post = ShopPost(shop_id=shop.id, title=title, content=content, image=filename)
    db.session.add(post)
    db.session.commit()

    flash("Post created successfully! 📢")
    return redirect(url_for('profile'))

@app.route('/owner/offer/create', methods=['POST'])
@login_required
def create_offer():
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop:
        flash("Please create a shop first! ❌")
        return redirect(url_for('owner_dashboard'))

    title = request.form.get('title')
    description = request.form.get('description')
    discount = request.form.get('discount_percentage')
    coupon = request.form.get('coupon_code')
    start_str = request.form.get('start_date')
    end_str = request.form.get('end_date')
    offer_type = request.form.get('offer_type', 'Offer')
    banner_file = request.files.get('banner_image')

    if not title or not description or not discount or not start_str or not end_str:
        flash("Missing required fields for offer! ❌")
        return redirect(url_for('profile'))

    try:
        if 'T' in start_str:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        else:
            start_date = datetime.datetime.strptime(start_str, '%Y-%m-%d')
        
        if 'T' in end_str:
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%dT%H:%M')
        else:
            end_date = datetime.datetime.strptime(end_str, '%Y-%m-%d')
    except Exception as date_err:
        print("ERROR PARSING DATES:", date_err)
        flash("Invalid date format! ❌")
        return redirect(url_for('profile'))

    filename = None
    if banner_file and banner_file.filename != "":
        filename = secure_filename(banner_file.filename)
        filename = f"offer_{shop.id}_{int(datetime.datetime.now().timestamp())}_{filename}"
        banner_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    else:
        flash("Banner image is required for offers! ❌")
        return redirect(url_for('profile'))

    offer = ShopOffer(
        shop_id=shop.id,
        title=title,
        description=description,
        banner_image=filename,
        discount_percentage=float(discount),
        coupon_code=coupon or None,
        start_date=start_date,
        end_date=end_date,
        offer_type=offer_type
    )
    db.session.add(offer)
    db.session.commit()

    flash("Offer created successfully! 🏷️")
    return redirect(url_for('profile'))

@app.route('/owner/post/delete/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
    
    post = ShopPost.query.get_or_404(post_id)
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop or post.shop_id != shop.id:
        flash("Unauthorized action! ❌")
        return redirect(url_for('profile'))

    db.session.delete(post)
    db.session.commit()
    flash("Post deleted successfully! 🗑️")
    return redirect(url_for('profile'))

@app.route('/owner/offer/delete/<int:offer_id>', methods=['POST'])
@login_required
def delete_offer(offer_id):
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
    
    offer = ShopOffer.query.get_or_404(offer_id)
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    if not shop or offer.shop_id != shop.id:
        flash("Unauthorized action! ❌")
        return redirect(url_for('profile'))

    db.session.delete(offer)
    db.session.commit()
    flash("Offer deleted successfully! 🗑️")
    return redirect(url_for('profile'))

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
    verifications = ShopVerification.query.all()

    return render_template("admin_dashboard.html", users=users, shops=shops, orders=orders, verifications=verifications)


@app.route('/admin/verification/approve/<int:verification_id>', methods=['POST'])
@login_required
def admin_verification_approve(verification_id):
    if current_user.role != "admin":
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    verification = ShopVerification.query.get_or_404(verification_id)
    verification.status = "Verified"
    db.session.commit()
    flash(f"Shop '{verification.shop.name}' has been successfully verified! ✨")
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/verification/reject/<int:verification_id>', methods=['POST'])
@login_required
def admin_verification_reject(verification_id):
    if current_user.role != "admin":
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))
        
    verification = ShopVerification.query.get_or_404(verification_id)
    verification.status = "Rejected"
    db.session.commit()
    flash(f"Verification request for '{verification.shop.name}' was rejected.")
    return redirect(url_for('admin_dashboard'))


# ==========================================
# SUPER ADMIN CONTROLLERS & SERVICES
# ==========================================

@app.route('/superadmin')
@app.route('/superadmin/dashboard')
@login_required
@super_admin_required
def superadmin_dashboard():
    users = User.query.all()
    shops = Shop.query.all()
    products = Product.query.all()
    orders = Order.query.all()
    verifications = ShopVerification.query.order_by(ShopVerification.submitted_at.desc()).all()
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).all()
    notifications = Notification.query.order_by(Notification.created_at.desc()).all()
    
    # Calculate key metrics
    total_users = len(users)
    total_owners = sum(1 for u in users if u.role == 'owner')
    total_products = len(products)
    total_orders = len(orders)
    verified_shops = sum(1 for s in shops if s.is_verified)
    
    # Active users count: verified and not suspended
    active_users = sum(1 for u in users if u.is_active)
    
    # Total revenue from completed/paid/delivered orders
    total_revenue = sum(o.total for o in orders if o.status in ['Completed', 'Paid', 'Delivered'])
    
    # Chatbot and recommendation counts from analytics logs
    chatbot_clicks = sum(1 for a in analytics if a.event_type == 'chatbot_chat')
    recommendation_clicks = sum(1 for a in analytics if a.event_type == 'recommender_use')
    active_connections = sum(len(s.connections) for s in shops)
    
    return render_template(
        "superadmin_dashboard.html",
        users=users,
        shops=shops,
        products=products,
        orders=orders,
        verifications=verifications,
        analytics=analytics[:100],  # Limit to latest 100 entries for efficiency
        notifications=notifications[:100],
        total_users=total_users,
        total_owners=total_owners,
        total_products=total_products,
        total_orders=total_orders,
        verified_shops=verified_shops,
        active_users=active_users,
        total_revenue=total_revenue,
        chatbot_clicks=chatbot_clicks,
        recommendation_clicks=recommendation_clicks,
        active_connections=active_connections
    )

@app.route('/superadmin/user/toggle_suspend/<int:user_id>', methods=['POST'])
@login_required
@super_admin_required
def superadmin_toggle_suspend(user_id):
    user = User.query.get_or_404(user_id)
    if user.email == os.environ.get("SUPER_ADMIN_EMAIL"):
        flash("Safety Lock: You cannot suspend your own super admin account! ❌")
        return redirect(url_for('superadmin_dashboard'))
        
    user.is_suspended = not user.is_suspended
    db.session.commit()
    
    action = "suspended" if user.is_suspended else "reactivated"
    print(f"[SUPERADMIN LOG] User {user.username} (ID: {user.id}) account status changed to {action.upper()}.")
    
    # Write to Analytics log
    try:
        log = Analytics(
            event_type="user_ban_toggle",
            user_id=current_user.id,
            details=f"Super Admin {action} user '{user.username}' (Email: {user.email})"
        )
        db.session.add(log)
    except Exception as e:
        print("[SUPERADMIN] Failed to write ban log:", e)
        
    # Send Notification to targeted user
    notif = Notification(
        user_id=user.id,
        title=f"Account Updates: {action.title()} Status",
        message=f"Your MiniMartPro account has been officially {action} by the Super Administration Hub. If you believe this is an error, please reach out to support."
    )
    db.session.add(notif)
    db.session.commit()
    
    flash(f"User account '{user.username}' successfully {action.upper()}! 🛡️")
    return redirect(url_for('superadmin_dashboard'))

@app.route('/superadmin/shop/toggle_disable/<int:shop_id>', methods=['POST'])
@login_required
@super_admin_required
def superadmin_toggle_disable(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    shop.is_disabled = not shop.is_disabled
    db.session.commit()
    
    action = "disabled" if shop.is_disabled else "enabled"
    print(f"[SUPERADMIN LOG] Shop '{shop.name}' (ID: {shop.id}) storefront status changed to {action.upper()}.")
    
    # Write to Analytics log
    try:
        log = Analytics(
            event_type="shop_disable_toggle",
            user_id=current_user.id,
            details=f"Super Admin {action} shop '{shop.name}' (Code: {shop.shop_code})"
        )
        db.session.add(log)
    except Exception as e:
        print("[SUPERADMIN] Failed to write shop log:", e)
        
    # Send Notification to owner
    if shop.owner:
        notif = Notification(
            user_id=shop.owner.id,
            title=f"Storefront Alerts: {action.title()} Status",
            message=f"Your store '{shop.name}' has been {action} by the Super Administration Hub. Customers cannot view your products while it is disabled."
        )
        db.session.add(notif)
        
    db.session.commit()
    flash(f"Storefront '{shop.name}' successfully {action.upper()}! 🏪")
    return redirect(url_for('superadmin_dashboard'))

@app.route('/superadmin/verification/action/<int:verification_id>/<string:action>', methods=['POST'])
@login_required
@super_admin_required
def superadmin_verification_action(verification_id, action):
    verification = ShopVerification.query.get_or_404(verification_id)
    
    if action == 'approve':
        verification.status = 'Verified'
        verification.verification_status = 'Verified'
        msg_content = "Congratulations! Your store verification request has been APPROVED by the Super Administration Hub! You have unlocked your magical glowing verified badge. ✨"
        flash(f"Storefront '{verification.shop.name}' successfully VERIFIED! Badge active. ❇️")
    elif action == 'reject':
        verification.status = 'Rejected'
        verification.verification_status = 'Rejected'
        msg_content = "Your storefront verification request was rejected. Please review your credentials and submit accurate photos."
        flash(f"Verification request for '{verification.shop.name}' has been REJECTED! ❌")
    elif action == 'request_reupload':
        verification.status = 'Under Review'
        verification.verification_status = 'Under Review'
        # Clear paths to trigger owner re-upload form state
        verification.front_image = ""
        verification.inside_image = ""
        verification.owner_photo = ""
        verification.shop_photo = ""
        msg_content = "The Super Administration Hub requests you to re-upload your verification proofs. Please visit your shop verification console and upload clear images."
        flash(f"Re-upload request sent successfully to shop '{verification.shop.name}'! 🔄")
    else:
        flash("Invalid verification action specified! ❌")
        return redirect(url_for('superadmin_dashboard'))
        
    print(f"[SUPERADMIN LOG] Shop Verification ID {verification.id} ({verification.shop.name}) action: {action.upper()}.")
    
    # Write to Analytics log
    try:
        log = Analytics(
            event_type="shop_verification_action",
            user_id=current_user.id,
            details=f"Super Admin processed verification for '{verification.shop.name}': Action={action}"
        )
        db.session.add(log)
    except Exception as e:
        print("[SUPERADMIN] Failed to write verification log:", e)
        
    # Send Notification to owner
    if verification.shop.owner:
        notif = Notification(
            user_id=verification.shop.owner.id,
            title="Branding Alert: Shop Verification Update",
            message=msg_content
        )
        db.session.add(notif)
        
    db.session.commit()
    return redirect(url_for('superadmin_dashboard'))

@app.route('/superadmin/notifications/broadcast', methods=['POST'])
@login_required
@super_admin_required
def superadmin_broadcast_notification():
    title = request.form.get('title')
    message = request.form.get('message')
    target_user_id = request.form.get('target_user_id')
    
    if not title or not message:
        flash("Missing title or message body! ❌")
        return redirect(url_for('superadmin_dashboard'))
        
    uid = None
    target_name = "Global Broadcast"
    if target_user_id and target_user_id != 'all':
        try:
            uid = int(target_user_id)
            target_user = User.query.get(uid)
            if target_user:
                target_name = f"User '{target_user.username}'"
        except:
            uid = None
            
    notif = Notification(
        user_id=uid,
        title=title,
        message=message
    )
    db.session.add(notif)
    
    # Log analytics event
    try:
        log = Analytics(
            event_type="admin_notification_sent",
            user_id=current_user.id,
            details=f"Super Admin broadcasted notification '{title}' to: {target_name}"
        )
        db.session.add(log)
    except:
        pass
        
    db.session.commit()
    flash(f"Notification broadcasted successfully to {target_name.upper()}! 📢")
    return redirect(url_for('superadmin_dashboard'))

@app.route('/api/notification/read/<int:notification_id>', methods=['POST'])
@login_required
def read_notification(notification_id):
    notif = Notification.query.get_or_404(notification_id)
    if notif.user_id and notif.user_id != current_user.id:
        return jsonify({"status": "error", "message": "Unauthorized access."}), 403
        
    notif.is_read = True
    db.session.commit()
    return jsonify({"status": "success", "message": "Notification marked as read."})

@app.route('/api/notification/clear_all', methods=['POST'])
@login_required
def clear_all_notifications():
    # Mark user specific and unread global notifications as read
    notifs = Notification.query.filter(
        (Notification.user_id == current_user.id) | (Notification.user_id == None)
    ).all()
    for n in notifs:
        n.is_read = True
    db.session.commit()
    return jsonify({"status": "success", "message": "All notifications marked as read."})





@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_google_maps_api_key():
    return {
        'google_maps_api_key': os.environ.get("GOOGLE_MAPS_API_KEY", "")
    }


# ================= HOME =================
@app.route('/')
def index():
    # 1. Fetch Trending Offers (highest discount active offers)
    now = datetime.datetime.now()
    active_offers = ShopOffer.query.filter(ShopOffer.start_date <= now, ShopOffer.end_date >= now).all()
    
    trending_offers = sorted(active_offers, key=lambda o: o.discount_percentage, reverse=True)[:6]

    # 2. Today's Deals (Active offers ending soon)
    today_deals = []
    tomorrow = now + datetime.timedelta(days=1)
    for o in active_offers:
        if o.end_date <= tomorrow:
            today_deals.append(o)
    if not today_deals:
        # Fallback to general active offers
        today_deals = active_offers[:6]

    # 3. Connected Shop Offers
    connected_shop_offers = []
    recommended_shops = []
    if current_user.is_authenticated and current_user.role == 'customer':
        connections = ShopConnection.query.filter_by(customer_id=current_user.id).all()
        connected_shop_ids = [c.shop_id for c in connections]
        if connected_shop_ids:
            connected_shop_offers = ShopOffer.query.filter(
                ShopOffer.shop_id.in_(connected_shop_ids),
                ShopOffer.start_date <= now,
                ShopOffer.end_date >= now
            ).order_by(ShopOffer.id.desc()).all()

            # Recommend shops user is NOT connected to
            recommended_shops = Shop.query.filter(~Shop.id.in_(connected_shop_ids)).limit(4).all()
        else:
            recommended_shops = Shop.query.limit(4).all()
    else:
        recommended_shops = Shop.query.limit(4).all()

    return render_template(
        "index.html",
        trending_offers=trending_offers,
        today_deals=today_deals,
        connected_shop_offers=connected_shop_offers,
        recommended_shops=recommended_shops
    )


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
    
    # Connection status
    is_connected = False
    if current_user.role == 'customer':
        conn = ShopConnection.query.filter_by(customer_id=current_user.id, shop_id=shop.id).first()
        is_connected = conn is not None

    # Offers and posts
    offers = ShopOffer.query.filter_by(shop_id=shop.id).order_by(ShopOffer.id.desc()).all()
    posts = ShopPost.query.filter_by(shop_id=shop.id).order_by(ShopPost.id.desc()).all()

    # Split offers into active/upcoming and expired
    now = datetime.datetime.now()
    active_offers = [o for o in offers if o.start_date <= now <= o.end_date]
    upcoming_offers = [o for o in offers if now < o.start_date]
    expired_offers = [o for o in offers if now > o.end_date]

    # Combine active and upcoming for the top display
    display_offers = active_offers + upcoming_offers

    # Ratings
    ratings = ShopRating.query.filter_by(shop_id=shop.id).all()

    # Recommendations (using limit=8 to populate the compact slider)
    try:
        recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, limit=8)
    except:
        recommendations = []
        
    return render_template(
        "shop_products.html",
        shop=shop,
        products=products,
        recommendations=recommendations,
        is_connected=is_connected,
        display_offers=display_offers,
        expired_offers=expired_offers,
        posts=posts,
        ratings=ratings
    )


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
            upload_path = app.config['UPLOAD_FOLDER']
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)
            image.save(os.path.join(upload_path, filename))

        try:
            product = Product(
                name=request.form['name'],
                description=request.form['description'],
                price=float(request.form['price']),
                price_unit=request.form.get('price_unit', 'piece'),
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


# ================= EDIT PRODUCT =================
@app.route('/edit_product/<int:product_id>', methods=['GET', 'POST'])
@login_required
def edit_product(product_id):
    if current_user.role != "owner":
        return redirect(url_for('index'))

    product = Product.query.get_or_404(product_id)
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    
    if not shop or product.shop_id != shop.id:
        flash("Unauthorized access ❌")
        return redirect(url_for('owner_dashboard'))

    if request.method == 'POST':
        image = request.files.get('image')
        if image and image.filename != "":
            filename = secure_filename(image.filename)
            upload_path = app.config['UPLOAD_FOLDER']
            if not os.path.exists(upload_path):
                os.makedirs(upload_path)
            image.save(os.path.join(upload_path, filename))
            product.image = filename

        try:
            product.name = request.form['name']
            product.description = request.form['description']
            product.price = float(request.form['price'])
            product.price_unit = request.form.get('price_unit', 'piece')
            product.stock = float(request.form['stock'])
            
            db.session.commit()
            flash("Product Updated Successfully ✅")
            return redirect(url_for('owner_dashboard'))
        except Exception as e:
            db.session.rollback()
            flash("Error updating product. Please check your inputs.")

    return render_template("edit_product.html", product=product)


# ================= DELETE PRODUCT =================
@app.route('/delete_product/<int:product_id>', methods=['POST'])
@login_required
def delete_product(product_id):
    if current_user.role != "owner":
        return redirect(url_for('index'))

    product = Product.query.get_or_404(product_id)
    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    
    if not shop or product.shop_id != shop.id:
        flash("Unauthorized access ❌")
        return redirect(url_for('owner_dashboard'))

    try:
        # 1. Nullify the product references in OrderItem to maintain order history.
        OrderItem.query.filter_by(product_id=product.id).update({OrderItem.product_id: None})
        
        # 2. Delete ratings for this product.
        ProductRating.query.filter_by(product_id=product.id).delete()
        
        # 3. Delete the product itself.
        db.session.delete(product)
        db.session.commit()
        
        flash("Product Deleted Successfully ✅")
    except Exception as e:
        db.session.rollback()
        print("ERROR: Product deletion failed:", str(e))
        flash("Error deleting product. Please try again.")

    return redirect(url_for('owner_dashboard'))


# ================= PRODUCT DETAILS =================
@app.route('/product/<int:product_id>')
@login_required
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    
    recommendations = []
    if current_user.role == 'customer':
        try:
            recommendations = recommender.get_hybrid_recommendations(user_id=current_user.id, limit=4)
        except:
            pass
            
    return render_template("product_details.html", product=product, shop=product.shop, recommendations=recommendations)


@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    try:
        quantity = float(request.form['quantity'])
    except (ValueError, TypeError):
        flash("Invalid quantity entered ❌")
        return redirect(request.referrer)

    unit = request.form.get('unit', 'piece')

    if quantity <= 0:
        return redirect(request.referrer)

    product = db.session.get(Product, product_id)
    if not product:
        flash("Product not found ❌")
        return redirect(request.referrer)

    # Convert the user quantity to base pricing unit quantity
    qty_in_price_unit = convert_to_price_unit(quantity, unit, product.price_unit)

    if 'cart' not in session:
        session['cart'] = {}

    cart = session['cart']
    current_in_cart = float(cart.get(str(product_id), 0.0))
    total_requested = current_in_cart + qty_in_price_unit

    if product.stock < total_requested:
        flash(f"Not enough stock for {product.name}! Available stock: {format_display_quantity(product.stock, product.price_unit)} ❌")
        return redirect(request.referrer)

    cart[str(product_id)] = total_requested
    session['cart'] = cart
    session.modified = True

    flash(f"Added {quantity} {unit} of {product.name} to Cart ✅")
    return redirect(request.referrer)


# ================= CART =================
@app.route('/cart')
@login_required
def cart():
    cart = session.get('cart', {})
    items = []
    total = 0
    cart_product_ids = []
    shop = None

    for pid, qty in cart.items():
        product = db.session.get(Product, int(pid))
        if not product:
            continue

        cart_product_ids.append(int(pid))
        subtotal = product.price * qty
        total += subtotal

        # Set shop from the first item
        if not shop:
            shop = product.shop

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

    return render_template("cart.html", items=items, total=total, recommendations=recommendations, shop=shop)

@app.route('/owner_orders')
@login_required
def owner_orders():
    if current_user.role != "owner":
        return redirect(url_for('index'))

    shop = Shop.query.filter_by(owner_id=current_user.id).first()
    orders = Order.query.filter_by(shop_id=shop.id).order_by(Order.id.desc()).all()

    return render_template("owner_orders.html", orders=orders)

# ==========================================
# OWNER PAYMENT VERIFICATION ACTIONS
# ==========================================
@app.route('/owner/payment/verify/<int:payment_id>/approve', methods=['POST'])
@login_required
def owner_payment_approve(payment_id):
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))

    payment = UPIPayments.query.get_or_404(payment_id)
    payment.status = "Paid"
    
    # Auto accept the order when payment is approved
    if payment.order.status == "Pending":
        payment.order.status = "Accepted"
        
    db.session.commit()
    flash(f"Payment approved successfully for Order #{payment.order_id}! Order Accepted. ✅")
    return redirect(url_for('owner_orders'))


@app.route('/owner/payment/verify/<int:payment_id>/reject', methods=['POST'])
@login_required
def owner_payment_reject(payment_id):
    if current_user.role != 'owner':
        flash("Unauthorized access! ❌")
        return redirect(url_for('index'))

    payment = UPIPayments.query.get_or_404(payment_id)
    payment.status = "Failed"
    db.session.commit()
    flash(f"Payment rejected for Order #{payment.order_id}. status marked Failed.")
    return redirect(url_for('owner_orders'))

# ================= PLACE ORDER =================
@app.route('/place_order', methods=['POST'])
@login_required
def place_order():
    cart = session.get('cart', {})

    if not cart:
        flash("Cart is empty")
        return redirect(url_for('shop_list'))

    payment_method = request.form['payment']
    transaction_id = request.form.get('transaction_id')
    screenshot_file = request.files.get('payment_screenshot')

    first_product = db.session.get(Product, int(list(cart.keys())[0]))
    if not first_product:
        flash("Invalid product in cart")
        session.pop('cart', None)
        return redirect(url_for('shop_list'))
        
    shop_id = first_product.shop_id

    try:
        order = Order(
            customer_id=current_user.id,
            shop_id=shop_id,
            total=0,
            payment_method=payment_method,
            status="Pending"
        )
        db.session.add(order)
        db.session.flush()

        total = 0

        for pid, qty in cart.items():
            product = db.session.get(Product, int(pid))
            if not product:
                raise ValueError(f"Product not found")

            if product.stock < qty:
                raise ValueError(f"Not enough stock for {product.name}")

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

        # Handle UPI payments screenshot proof
        if payment_method != "Cash on Delivery" and screenshot_file and screenshot_file.filename != "":
            filename = secure_filename(screenshot_file.filename)
            filename = f"pay_{order.id}_{int(datetime.datetime.now().timestamp())}_{filename}"
            screenshot_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            
            upi_payment = UPIPayments(
                order_id=order.id,
                transaction_id=transaction_id,
                screenshot=filename,
                amount=total,
                status="Under Verification"
            )
            db.session.add(upi_payment)
            flash("Order placed successfully! Payment screenshot uploaded for review. ⏱️")
        else:
            flash("Order Placed Successfully via COD!")

        db.session.commit()

        session.pop('cart', None)

        # Retrain recommender async or synchronously to reflect new order
        try:
            recommender.train_models()
        except:
            pass

        return redirect(url_for('my_orders'))

    except ValueError as val_err:
        db.session.rollback()
        flash(str(val_err))
        return redirect(url_for('cart'))
    except Exception as e:
        db.session.rollback()
        print("ERROR: Order placement failed:", str(e))
        flash("An error occurred while placing order. Please try again.")
        return redirect(url_for('cart'))


# ================= UPDATE STATUS =================
@app.route('/update_status/<int:order_id>')
@login_required
def update_status(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        flash("Order not found ❌")
        return redirect(request.referrer)

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

# ==========================================
# GPS LOCATION CACHING API FOR CUSTOMERS
# ==========================================
@app.route('/api/gps/log', methods=['POST'])
@login_required
def api_gps_log():
    data = request.get_json() or {}
    lat = data.get('latitude')
    lng = data.get('longitude')
    
    if lat is not None and lng is not None:
        try:
            # Check if user already has a GPS log, else create
            log = GPSLogs.query.filter_by(user_id=current_user.id).first()
            if not log:
                log = GPSLogs(user_id=current_user.id, latitude=float(lat), longitude=float(lng))
                db.session.add(log)
            else:
                log.latitude = float(lat)
                log.longitude = float(lng)
                log.updated_at = datetime.datetime.utcnow()
                
            db.session.commit()
            return jsonify({"status": "success", "message": "Proximity logs updated."})
        except Exception as err:
            db.session.rollback()
            return jsonify({"status": "error", "message": str(err)}), 500
            
    return jsonify({"status": "error", "message": "Missing coordinates."}), 400

# ================= CHATBOT =================
@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json() or {}
    message = data.get('message', '')
    context_data = data.get('context', {})
    
    # Check if user is logged in to provide personalized context
    user = current_user if (current_user and current_user.is_authenticated) else None
    
    # Process message with role context, browse details, and active cart
    response = chatbot.process_message(
        message, 
        user=user, 
        context_data=context_data, 
        cart=session.get('cart', {})
    )
    
    # Log chatbot analytics event
    try:
        uid = current_user.id if current_user.is_authenticated else None
        log_event = Analytics(
            event_type='chatbot_chat',
            user_id=uid,
            details=f"User queried: '{message[:60]}...'"
        )
        db.session.add(log_event)
        db.session.commit()
    except Exception as analytics_err:
        db.session.rollback()
        print("[DEBUG LOG] Chatbot analytics log failed:", analytics_err)
    
    # 1. Handle CUSTOMER multiple product cart additions
    if response.get("action") == "add_to_cart":
        products_to_add = response.get("products", [])
        if not products_to_add and response.get("product_id"):
            products_to_add = [{
                "product_id": response.get("product_id"),
                "quantity": response.get("quantity", 1),
                "unit": "piece"
            }]
            
        if 'cart' not in session:
            session['cart'] = {}
        cart = session['cart']
        
        for item in products_to_add:
            pid = str(item.get("product_id"))
            qty = float(item.get("quantity", 1.0))
            unit = item.get("unit", "piece")
            
            p = db.session.get(Product, int(pid))
            if p:
                # Convert user unit to base price unit
                qty_in_price_unit = convert_to_price_unit(qty, unit, p.price_unit)
                cart[pid] = float(cart.get(pid, 0.0)) + qty_in_price_unit
                
        session['cart'] = cart
        session.modified = True

    # 2. Handle OWNER natural language product creation
    elif response.get("action") == "add_product" and user and user.role == "owner":
        p_name = response.get("product_name")
        qty = response.get("quantity")
        unit = response.get("unit", "piece")
        price = response.get("price")
        
        shop = Shop.query.filter_by(owner_id=user.id).first()
        if shop and p_name and qty is not None and price is not None:
            try:
                # Update stock if already exists, else create new
                existing_p = Product.query.filter_by(shop_id=shop.id, name=p_name).first()
                if existing_p:
                    existing_p.stock += float(qty)
                    db.session.commit()
                    response["message"] = f"✅ **Updated product inventory!** Increased *'{existing_p.name}'* stock by {qty} {unit}. New total stock: {existing_p.stock} {existing_p.price_unit}."
                else:
                    new_p = Product(
                        name=p_name,
                        description=f"Auto-generated via AI Assistant.",
                        price=float(price),
                        price_unit=unit,
                        stock=float(qty),
                        shop_id=shop.id
                    )
                    db.session.add(new_p)
                    db.session.commit()
                    response["message"] = f"✅ **Product Created Successfully!**\n\n*   **Name:** {p_name}\n*   **Price:** ₹ {price} per {unit}\n*   **Initial Stock:** {qty} {unit}\n\nInventory updated."
            except Exception as db_err:
                db.session.rollback()
                response["message"] = f"❌ **Database error while creating product:** {str(db_err)}"

    # 3. Handle OWNER natural language stock override adjustment
    elif response.get("action") == "update_stock" and user and user.role == "owner":
        p_name = response.get("product_name")
        qty = response.get("quantity")
        
        shop = Shop.query.filter_by(owner_id=user.id).first()
        if shop and p_name and qty is not None:
            try:
                products = Product.query.filter(Product.shop_id == shop.id, Product.name.ilike(f"%{p_name}%")).all()
                if products:
                    p = products[0]
                    p.stock = float(qty)
                    db.session.commit()
                    response["message"] = f"✅ **Stock Adjusted Successfully!**\n\n*   **Product:** {p.name}\n*   **New Stock:** {p.stock} {p.price_unit}\n\nInventory list updated."
                else:
                    response["message"] = f"❌ Product *'{p_name}'* not found in your inventory. Did you mean to *'Add'* it?"
            except Exception as db_err:
                db.session.rollback()
                response["message"] = f"❌ **Database error adjusting stock:** {str(db_err)}"
                
    return jsonify(response)

# ================= INIT =================
def check_and_update_db_schema():
    if not app.config.get('SQLALCHEMY_DATABASE_URI'):
        return
    try:
        from sqlalchemy import text
        with db.engine.begin() as conn:
            # 1. User & Shop table suspensions/disabled migrations (SQLite & PostgreSQL support)
            try:
                if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;'))
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS otp VARCHAR(6);'))
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS otp_expiry TIMESTAMP;'))
                    conn.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN DEFAULT FALSE;'))
                else:
                    try:
                        conn.execute(text('ALTER TABLE "user" ADD COLUMN is_suspended BOOLEAN DEFAULT FALSE;'))
                    except Exception as e:
                        pass # Column may already exist
                print("User table suspension columns verified/created successfully.")
            except Exception as schema_err:
                print("User table suspension migration warning:", schema_err)

            try:
                if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                    conn.execute(text('ALTER TABLE shop ADD COLUMN IF NOT EXISTS is_disabled BOOLEAN DEFAULT FALSE;'))
                else:
                    try:
                        conn.execute(text('ALTER TABLE shop ADD COLUMN is_disabled BOOLEAN DEFAULT FALSE;'))
                    except Exception as e:
                        pass # Column may already exist
                print("Shop table disabled columns verified/created successfully.")
            except Exception as schema_err:
                print("Shop table disabled migration warning:", schema_err)

            # 2. Add price_unit column to product table (SQLite and PostgreSQL)
            try:
                if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                    conn.execute(text('ALTER TABLE product ADD COLUMN IF NOT EXISTS price_unit VARCHAR(20) DEFAULT \'piece\';'))
                else:
                    conn.execute(text("ALTER TABLE product ADD COLUMN price_unit VARCHAR(20) DEFAULT 'piece';"))
                print("Added column price_unit to product table.")
            except Exception as col_err:
                print("Column price_unit may already exist or cannot be added:", str(col_err))

            # 3. Add custom columns to shop table (SQLite and PostgreSQL)
            for col, col_type in [("logo", "VARCHAR(200)"), ("banner_image", "VARCHAR(200)"), ("category", "VARCHAR(100) DEFAULT 'General'"), ("bio", "VARCHAR(500)")]:
                try:
                    if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                        conn.execute(text(f'ALTER TABLE shop ADD COLUMN IF NOT EXISTS {col} {col_type};'))
                    else:
                        conn.execute(text(f'ALTER TABLE shop ADD COLUMN {col} {col_type};'))
                    print(f"Added column {col} to shop table.")
                except Exception as col_err:
                    print(f"Column {col} to shop may already exist or cannot be added:", str(col_err))

            # 4. Add created_at column to order table (SQLite and PostgreSQL)
            try:
                if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                    conn.execute(text('ALTER TABLE "order" ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;'))
                else:
                    conn.execute(text('ALTER TABLE "order" ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;'))
                print("Added column created_at to order table.")
            except Exception as col_err:
                print("Column created_at to order table may already exist or cannot be added:", str(col_err))

            # 5. Add new columns to shop_verification table (SQLite and PostgreSQL)
            verification_cols = [
                ("owner_photo", "VARCHAR(200)"),
                ("shop_photo", "VARCHAR(200)"),
                ("location_link", "VARCHAR(300)"),
                ("latitude", "DOUBLE PRECISION" if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI'] else "FLOAT"),
                ("longitude", "DOUBLE PRECISION" if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI'] else "FLOAT"),
                ("verification_status", "VARCHAR(20) DEFAULT 'Pending'"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            ]
            for col, col_type in verification_cols:
                try:
                    if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                        conn.execute(text(f'ALTER TABLE shop_verification ADD COLUMN IF NOT EXISTS {col} {col_type};'))
                    else:
                        conn.execute(text(f'ALTER TABLE shop_verification ADD COLUMN {col} {col_type};'))
                    print(f"Added column {col} to shop_verification table.")
                except Exception as col_err:
                    print(f"Column {col} to shop_verification may already exist or cannot be added: {str(col_err)}")

            # 6. Add new columns to payment_methods table (SQLite and PostgreSQL)
            payment_cols = [
                ("gpay_number", "VARCHAR(50)"),
                ("phonepe_number", "VARCHAR(50)"),
                ("paytm_number", "VARCHAR(50)"),
                ("cod_enabled", "BOOLEAN DEFAULT TRUE"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            ]
            for col, col_type in payment_cols:
                try:
                    if "postgresql" in app.config['SQLALCHEMY_DATABASE_URI']:
                        conn.execute(text(f'ALTER TABLE payment_methods ADD COLUMN IF NOT EXISTS {col} {col_type};'))
                    else:
                        conn.execute(text(f'ALTER TABLE payment_methods ADD COLUMN {col} {col_type};'))
                    print(f"Added column {col} to payment_methods table.")
                except Exception as col_err:
                    print(f"Column {col} to payment_methods may already exist or cannot be added: {str(col_err)}")
    except Exception as e:
        print("ERROR: Database schema check/update failed:", str(e))

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
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
import random
import string

db = SQLAlchemy()

# Generate Shop Code
def generate_shop_code():
    return "MM" + ''.join(random.choices(string.digits, k=4))


# =========================
# USER MODEL
# =========================
class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="customer")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    # OTP Verification Fields
    is_verified = db.Column(db.Boolean, default=False)
    otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)

    # ✅ ADD THIS (VERY IMPORTANT)
    @property
    def is_active(self):
        return self.is_verified
   
    # Relationships
    shop = db.relationship('Shop', backref='owner', uselist=False, lazy=True)
    orders = db.relationship('Order', backref='customer', lazy=True)


# =========================
# SHOP MODEL
# =========================
class Shop(db.Model):
    __tablename__ = 'shop'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.String(200))
    shop_code = db.Column(db.String(10), unique=True, default=generate_shop_code)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    products = db.relationship('Product', backref='shop', lazy=True)
    orders = db.relationship('Order', backref='shop', lazy=True)

    @property
    def average_rating(self):
        ratings = ShopRating.query.filter_by(shop_id=self.id).all()
        if not ratings:
            return 0.0
        return round(sum(r.rating for r in ratings) / len(ratings), 1)


# =========================
# PRODUCT MODEL
# =========================
class Product(db.Model):
    __tablename__ = 'product'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.String(200))
    price = db.Column(db.Float, nullable=False)
    price_unit = db.Column(db.String(20), default="piece")
    stock = db.Column(db.Float)  # 🔥 support kg / grams
    image = db.Column(db.String(200))
    shop_id = db.Column(db.Integer, db.ForeignKey('shop.id'))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    order_items = db.relationship('OrderItem', backref='product', lazy=True)

    @property
    def average_rating(self):
        ratings = ProductRating.query.filter_by(product_id=self.id).all()
        if not ratings:
            return 0.0
        return round(sum(r.rating for r in ratings) / len(ratings), 1)


# =========================
# ORDER MODEL
# =========================
class Order(db.Model):
    __tablename__ = 'order'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    shop_id = db.Column(db.Integer, db.ForeignKey('shop.id'))
    total = db.Column(db.Float, default=0)
    status = db.Column(db.String(20), default="Pending")
    payment_method = db.Column(db.String(20))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    items = db.relationship(
        'OrderItem',
        backref='order',
        lazy=True,
        cascade="all, delete-orphan"
    )


# =========================
# ORDER ITEM MODEL
# =========================
class OrderItem(db.Model):
    __tablename__ = 'order_item'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'))
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))

    # 🔥 decimal quantity (kg / grams)
    quantity = db.Column(db.Float)

    status = db.Column(db.String(20), default="Pending")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

# =========================
# RATING MODELS
# =========================
class ShopRating(db.Model):
    __tablename__ = 'shop_rating'

    id = db.Column(db.Integer, primary_key=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shop.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rating = db.Column(db.Integer, nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

class ProductRating(db.Model):
    __tablename__ = 'product_rating'

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    rating = db.Column(db.Integer, nullable=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
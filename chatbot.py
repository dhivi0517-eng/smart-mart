import os
import json
import re
import datetime
from sqlalchemy import func
from models import db, User, Shop, Product, Order, OrderItem, ShopOffer, ShopConnection, Wishlist

# Configure Gemini API Key
api_key = os.environ.get("GEMINI_API_KEY", "")

class Chatbot:
    def __init__(self):
        self.client = None
        if api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"Failed to initialize Gemini Client: {e}")

    def get_owner_context(self, user):
        """Fetch extensive store, inventory, and sales analytics context for the Shop Owner."""
        shop = Shop.query.filter_by(owner_id=user.id).first()
        if not shop:
            return "No shop is currently associated with this owner account."

        products = Product.query.filter_by(shop_id=shop.id).all()
        offers = ShopOffer.query.filter_by(shop_id=shop.id).all()
        connections_count = ShopConnection.query.filter_by(shop_id=shop.id).count()
        orders = Order.query.filter_by(shop_id=shop.id).all()
        
        # Analytics calculations
        today = datetime.date.today()
        today_orders = [o for o in orders if o.created_at and o.created_at.date() == today]
        today_sales_count = len(today_orders)
        today_revenue = sum(o.total for o in today_orders)
        
        total_revenue = sum(o.total for o in orders)
        total_orders_count = len(orders)
        
        # Low stock products (stock < 10 pieces or < 15 kg/litres)
        low_stock_items = [p for p in products if p.stock is not None and p.stock < (15.0 if p.price_unit in ['kg', 'litre'] else 10.0)]
        
        # Most sold products
        sold_stats = db.session.query(
            Product.name, func.sum(OrderItem.quantity)
        ).join(OrderItem, Product.id == OrderItem.product_id)\
         .filter(Product.shop_id == shop.id)\
         .group_by(Product.name)\
         .order_by(func.sum(OrderItem.quantity).desc())\
         .limit(5).all()
         
        most_sold_desc = ", ".join([f"{name} ({int(qty)} sold)" for name, qty in sold_stats]) if sold_stats else "None ordered yet"

        # Construct Context Text
        context = f"""
=== OWNER SHOP DATA ===
Shop Name: "{shop.name}"
Category: {shop.category}
Shop Code: {shop.shop_code}
Connected Customers: {connections_count}
Active Products in Store: {len(products)}

=== CURRENT INVENTORY ===
{chr(10).join([f"- ID: {p.id}, {p.name}: price ₹{p.price}/{p.price_unit}, stock: {p.stock} ({'LOW STOCK' if p in low_stock_items else 'Healthy'})" for p in products])}

=== SALES ANALYTICS SUMMARY ===
Today's Sales Count: {today_sales_count} orders
Today's Revenue: ₹{today_revenue:.2f}
Total Shop Revenue: ₹{total_revenue:.2f}
Total Orders Received: {total_orders_count}
Low Stock Products needing restock: {", ".join([p.name for p in low_stock_items]) if low_stock_items else "None! All stock levels healthy."}
Top Selling Products: {most_sold_desc}

=== PROMOTIONS & OFFERS ===
{chr(10).join([f"- Offer: '{o.title}', discount: {o.discount_percentage}%, coupon: {o.coupon_code or 'None'}, type: {o.offer_type}, status: {o.status}" for o in offers]) if offers else "No promotional campaigns active currently."}
"""
        return context

    def get_customer_context(self, user, shop_id=None, cart=None):
        """Fetch customer profile, purchase history, cart items, and browsing shop inventories."""
        # Shopping history
        orders = Order.query.filter_by(customer_id=user.id).order_by(Order.id.desc()).all()
        past_purchased_products = db.session.query(Product.name).join(OrderItem, Product.id == OrderItem.product_id).join(Order, Order.id == OrderItem.order_id).filter(Order.customer_id == user.id).distinct().limit(10).all()
        purchase_history_desc = ", ".join([p[0] for p in past_purchased_products]) if past_purchased_products else "None (New customer)"

        # Connections
        connections = ShopConnection.query.filter_by(customer_id=user.id).all()
        connected_shop_names = ", ".join([c.shop.name for c in connections]) if connections else "None connected yet"

        # Active Cart status
        cart_desc = "Your cart is currently empty."
        if cart:
            cart_items = []
            for pid, qty in cart.items():
                p = db.session.get(Product, int(pid))
                if p:
                    cart_items.append(f"{qty} x {p.name} (from {p.shop.name})")
            if cart_items:
                cart_desc = "Items in cart currently:\n" + "\n".join([f"- {item}" for item in cart_items])

        # Current Shop browsing details
        shop_catalog = "No active store selected. Browse a store from the Shops list."
        current_shop_name = "None"
        active_offers_desc = "No promotions currently in this store."
        
        if shop_id:
            shop = db.session.get(Shop, int(shop_id))
            if shop:
                current_shop_name = shop.name
                products = Product.query.filter_by(shop_id=shop.id).all()
                shop_catalog = f"\nStore Catalog for \"{shop.name}\" (browsing currently):\n" + "\n".join([f"- ID: {p.id}, {p.name}: ₹{p.price} per {p.price_unit} (Stock: {p.stock})" for p in products])
                
                now = datetime.datetime.now()
                offers = ShopOffer.query.filter(ShopOffer.shop_id == shop.id, ShopOffer.start_date <= now, ShopOffer.end_date >= now).all()
                if offers:
                    active_offers_desc = "\nActive Promotions today:\n" + "\n".join([f"- {o.discount_percentage}% OFF on '{o.title}' (Coupon: {o.coupon_code or 'N/A'})" for o in offers])

        # Construct Context Text
        context = f"""
=== CUSTOMER PROFILE ===
Customer Name: {user.username}
Customer Username: @{user.username.lower()}
Connected Stores: {connected_shop_names}
Favorite/Previously Purchased Items: {purchase_history_desc}

=== CURRENT CART STATE ===
{cart_desc}

=== BROWSING STORE: "{current_shop_name}" ==={shop_catalog}
{active_offers_desc}
"""
        return context

    def process_message(self, message, user=None, context_data=None, cart=None):
        msg = message.strip()
        if not msg:
            return {"action": "reply", "message": "Please say something! I am here to help."}

        # Role-based validation
        role = "customer"
        if user:
            role = user.role

        # Generate Context-Aware system prompt instructions
        if role == "owner":
            db_context = self.get_owner_context(user)
            system_prompt = f"""You are the Advanced AI Business Assistant for MiniMartPro store owners.
Your role is to act as a professional business analyst, inventory manager, and administrative assistant.
You have FULL database awareness. Always reference exact inventory quantities, prices, and revenue statistics based on the live context below.

=== LIVE DATABASE CONTEXT ===
{db_context}

=== MANDATORY JSON OUTPUT FORMAT ===
You must ALWAYS respond with a valid JSON object. No markdown wrapping outside JSON, no backticks, no comments.
The JSON object must have exactly this structure:
{{
    "action": "reply" | "add_product" | "update_stock" | "view_analytics" | "create_offer" | "show_pending_orders",
    "message": "Write a professional, premium, and friendly response with detailed formatting, emojis, insights, or tables in HTML/markdown.",
    "product_name": "Name of product to add or update stock (only if action is add_product or update_stock)",
    "quantity": <float/null> (amount/stock to add or set. default to null if not needed),
    "unit": "kg" | "g" | "piece" | "litre" (only if action is add_product),
    "price": <float/null> (price per unit. only if action is add_product),
    "query_type": "today_sales" | "weekly_revenue" | "most_sold" | "low_stock" | "top_customers" | "best_offers" | "orders" (only if action is view_analytics)
}}

Instructions for intents:
1. Product additions (e.g. "Add 5kg rice product with 60 per kg"): Return action "add_product", parse correct values.
2. Stock updates (e.g. "Update tomato stock to 25kg" or "set stock of milk to 10"): Return action "update_stock".
3. Analytics/Stats requests (e.g. "sales today", "weekly revenue", "best selling items", "low stock"): Return action "view_analytics", set the proper query_type.
4. General inquiries: Return "reply" with business suggestions, restock advice, trending hours, etc.
"""
        else:
            # Customer Assistant
            shop_id = context_data.get("shop_id") if context_data else None
            db_context = self.get_customer_context(user, shop_id=shop_id, cart=cart)
            
            system_prompt = f"""You are the Premium AI Shopping Assistant for MiniMartPro customers.
Your role is to act like a friendly, expert local merchant and shopping assistant.
You welcome customers, suggest relevant products, guide them to deals, and manage their carts dynamically.

=== LIVE DATABASE CONTEXT ===
{db_context}

=== MANDATORY JSON OUTPUT FORMAT ===
You must ALWAYS respond with a valid JSON object. No markdown wrapping outside JSON, no backticks, no comments.
The JSON object must have exactly this structure:
{{
    "action": "reply" | "add_to_cart" | "view_cart" | "recommend_products" | "get_offers",
    "message": "Write a personalized, beautiful, and engaging response. Include warm emojis, pricing breakdowns, and bulleted lists where relevant.",
    "products": [
        {{"product_name": "Exact matching product name from catalog", "quantity": <float>, "unit": "kg" | "g" | "piece" | "litre"}}
    ] (only if action is add_to_cart. Supports adding multiple products at once!)
}}

Instructions for intents:
1. Adding products to cart (e.g. "Add 2kg onion and 1 packet of milk" or "get me 500g tomato"):
   - Read the browsing store catalog. Match product name.
   - Return action "add_to_cart" with parsed items inside "products" array.
   - If a product is not in the browsing shop catalog, reply politely stating it's unavailable or suggest an alternative.
2. View Cart: Return action "view_cart".
3. Recommendations (e.g. "what should I buy?", "personalized picks"): Return action "recommend_products".
4. Deals & Offers: Return action "get_offers".
"""

        # Fallback to local rule engine if Gemini Client is offline
        if not self.client:
            return self.local_fallback_process(msg, user, role, context_data, cart)

        try:
            from google.genai import types
            
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=msg,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    response_mime_type="application/json",
                ),
            )
            
            # Clean JSON response
            text = response.text.strip()
            if text.startswith("```json"):
                text = text.replace("```json", "", 1)
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            result = json.loads(text)
            
            # Handle post-processing of structural actions safely
            action = result.get("action", "reply")
            
            if role == "owner":
                if action == "add_product":
                    p_name = result.get("product_name", "")
                    qty = result.get("quantity")
                    unit = result.get("unit", "piece")
                    price = result.get("price")
                    
                    if not p_name or qty is None or price is None:
                        return {"action": "reply", "message": "❌ I recognized you wanted to add a product, but some details (quantity, price, or name) were missing. Try saying: *'Add 5kg rice product with ₹60 per kg'*."}
                    
                    return {
                        "action": "add_product",
                        "product_name": p_name,
                        "quantity": float(qty),
                        "unit": unit,
                        "price": float(price),
                        "message": f"🤖 **Natural Language Intent Decoded!**\n\nCreating product:\n*   **Name:** {p_name}\n*   **Stock:** {qty} {unit}\n*   **Price:** ₹ {price} per {unit}\n\n*Processing database insert...*"
                    }
                    
                elif action == "update_stock":
                    p_name = result.get("product_name", "")
                    qty = result.get("quantity")
                    
                    if not p_name or qty is None:
                        return {"action": "reply", "message": "❌ I recognized you wanted to update inventory stock, but I couldn't extract the product name or quantity. Try saying: *'Update tomato stock to 25kg'*."}
                        
                    return {
                        "action": "update_stock",
                        "product_name": p_name,
                        "quantity": float(qty),
                        "message": f"🤖 **Natural Language Intent Decoded!**\n\nSetting stock level of '{p_name}' to **{qty}**.\n\n*Updating inventory records...*"
                    }
                    
                elif action == "view_analytics":
                    q_type = result.get("query_type", "orders")
                    # Generate live DB responses for the query
                    db_response = self.execute_local_analytics(user, q_type)
                    return {
                        "action": "reply",
                        "message": db_response
                    }
            else:
                # Customer Actions
                if action == "add_to_cart":
                    parsed_products = result.get("products", [])
                    if not parsed_products:
                        return {"action": "reply", "message": "What products would you like to add to your cart? 🛒"}
                        
                    # Find all items and verify in active browsing shop
                    shop_id = context_data.get("shop_id") if context_data else None
                    if not shop_id:
                        return {"action": "reply", "message": "⚠️ Please select a store first from the Shops catalog before adding items to your cart!"}
                        
                    added_details = []
                    rejected_details = []
                    cart_actions = []
                    
                    for item in parsed_products:
                        p_name = item.get("product_name", "")
                        qty = item.get("quantity", 1.0)
                        unit = item.get("unit", "piece")
                        
                        # Search in browsing shop
                        products = Product.query.filter(Product.shop_id == shop_id, Product.name.ilike(f"%{p_name}%")).all()
                        if not products:
                            rejected_details.append(f"*{p_name}* (Not found in catalog)")
                            continue
                            
                        p = products[0]
                        if p.stock < qty:
                            rejected_details.append(f"*{p.name}* (Insufficient stock, available: {p.stock})")
                            continue
                            
                        added_details.append(f"**{qty} {unit}** of *{p.name}* (₹{p.price}/{p.price_unit})")
                        cart_actions.append({
                            "product_id": p.id,
                            "quantity": qty,
                            "unit": unit
                        })
                        
                    msg_reply = ""
                    if added_details:
                        msg_reply += "✅ **Added to Cart successfully!**\n" + "\n".join([f"- {item}" for item in added_details]) + "\n\n"
                    if rejected_details:
                        msg_reply += "⚠️ **Couldn't Add Some Items:**\n" + "\n".join([f"- {item}" for item in rejected_details])
                        
                    if not cart_actions:
                        return {"action": "reply", "message": msg_reply or "Sorry, I couldn't find those products in this store."}
                        
                    return {
                        "action": "add_to_cart",
                        "products": cart_actions,
                        "message": msg_reply
                    }
                    
            return result
            
        except Exception as e:
            print(f"Chatbot Gemini Error: {e}. Switching to Local Database Engine.")
            return self.local_fallback_process(msg, user, role, context_data, cart)

    def execute_local_analytics(self, user, query_type):
        """Execute complex queries directly on DB to guarantee accurate responses for Business Analytics."""
        shop = Shop.query.filter_by(owner_id=user.id).first()
        if not shop:
            return "Shop setup required."

        if query_type == "today_sales":
            today = datetime.date.today()
            orders = Order.query.filter(Order.shop_id == shop.id).all()
            today_orders = [o for o in orders if o.created_at and o.created_at.date() == today]
            revenue = sum(o.total for o in today_orders)
            return f"📊 **Today's Business Analytics:**\n\n*   **Total Orders Today:** {len(today_orders)}\n*   **Total Revenue Generated:** ₹ {revenue:.2f}\n\nKeep it up! Active customer engagement boosts conversion rates. 🚀"

        elif query_type == "weekly_revenue":
            seven_days_ago = datetime.datetime.now() - datetime.timedelta(days=7)
            orders = Order.query.filter(Order.shop_id == shop.id, Order.created_at >= seven_days_ago).all()
            revenue = sum(o.total for o in orders)
            return f"📈 **Weekly Revenue Summary:**\n\n*   **Total Orders (Last 7 Days):** {len(orders)}\n*   **Accumulated Revenue:** ₹ {revenue:.2f}\n\n*Suggestion:* Run a Daily Deal banner tomorrow during peak hours (5 PM - 8 PM) to elevate conversion by another 12%."

        elif query_type == "low_stock":
            products = Product.query.filter_by(shop_id=shop.id).all()
            low_stock_items = [p for p in products if p.stock is not None and p.stock < (15.0 if p.price_unit in ['kg', 'litre'] else 10.0)]
            if not low_stock_items:
                return "✅ **Stock Health Check:**\n\nAll product inventories are perfectly healthy! Excellent inventory management."
                
            desc = "⚠️ **Low Stock Alert!**\nThe following products need restocking immediately:\n\n"
            for p in low_stock_items:
                desc += f"*   **{p.name}** - Current Stock: `{p.stock} {p.price_unit}` (Threshold: {'15' if p.price_unit == 'kg' else '10'})\n"
            desc += "\n*Task Recommendation:* Say *'Update [product] stock to [amount]'* to instantly update these levels."
            return desc

        elif query_type == "most_sold":
            sold_stats = db.session.query(
                Product.name, func.sum(OrderItem.quantity)
            ).join(OrderItem, Product.id == OrderItem.product_id)\
             .filter(Product.shop_id == shop.id)\
             .group_by(Product.name)\
             .order_by(func.sum(OrderItem.quantity).desc())\
             .limit(5).all()
             
            if not sold_stats:
                return "📦 **Popular Products:**\nNo order receipts recorded yet. Best-selling lists will populate as orders complete."
                
            desc = "⭐️ **Best-Selling Products (Top 5):**\nHere are your store's most demanded items:\n\n"
            for i, (name, qty) in enumerate(sold_stats, 1):
                desc += f"{i}.  **{name}** - `{int(qty)} units sold`\n"
            desc += "\n*Strategy:* Bundle these products with slow-moving inventory in a custom daily deal discount offer."
            return desc

        elif query_type == "top_customers":
            top_users = db.session.query(
                User.username, func.sum(Order.total), func.count(Order.id)
            ).join(Order, User.id == Order.customer_id)\
             .filter(Order.shop_id == shop.id)\
             .group_by(User.username)\
             .order_by(func.sum(Order.total).desc())\
             .limit(3).all()
             
            if not top_users:
                return "🤝 **Customer Analytics:**\nNo customer purchase profiles available yet."
                
            desc = "👑 **Top Connected VIP Customers:**\nYour most loyal spenders:\n\n"
            for name, total, count in top_users:
                desc += f"*   **{name}** - Total Spent: `₹ {total:.2f}` ({count} orders)\n"
            desc += "\n*Marketing Tip:* Publish a custom **coupon code** post to thank them and retain their loyalty!"
            return desc

        return "I can generate reports, show sales metrics, list low-stock items, or highlight top selling products. Let me know what you need!"

    def local_fallback_process(self, msg, user, role, context_data=None, cart=None):
        """Highly intelligent database-aware offline process engine for both Owners and Customers."""
        msg_lower = msg.lower().strip()
        
        # OWNER LOCAL FALLBACK
        if role == "owner":
            shop = Shop.query.filter_by(owner_id=user.id).first()
            if not shop:
                return {"action": "reply", "message": "🏪 Setup a shop before managing inventory."}

            # 1. Product Addition regex: "add <name> <qty><unit> <price>"
            add_match = re.search(r'add\s+([\w\s]+?)\s*(?:product)?\s*(?:with|at|for)?\s*₹?\s*(\d+(?:\.\d+)?)\s*(?:per\s*)?(\w+)?', msg_lower)
            # Second regex check for: "Add 5kg rice product with 60 per kg"
            add_match2 = re.search(r'add\s+(\d+(?:\.\d+)?)\s*(\w+)\s+([\w\s]+?)\s*(?:product)?\s*(?:with|at|for)?\s*₹?\s*(\d+(?:\.\d+)?)', msg_lower)
            
            if add_match2:
                qty = float(add_match2.group(1))
                unit = add_match2.group(2)
                p_name = add_match2.group(3).strip()
                price = float(add_match2.group(4))
                
                return {
                    "action": "add_product",
                    "product_name": p_name,
                    "quantity": qty,
                    "unit": unit,
                    "price": price,
                    "message": f"⚙️ **[Local Fallback Decoded]** Adding **{qty} {unit}** of *'{p_name}'* at **₹ {price} per {unit}** to store."
                }
            elif add_match:
                p_name = add_match.group(1).strip()
                price = float(add_match.group(2))
                unit = add_match.group(3) or "piece"
                
                # Check if user mentioned quantity in text e.g., "5kg"
                qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(kg|g|piece|litre|pkg|box)', msg_lower)
                qty = float(qty_match.group(1)) if qty_match else 10.0
                unit = qty_match.group(2) if qty_match else unit
                
                return {
                    "action": "add_product",
                    "product_name": p_name,
                    "quantity": qty,
                    "unit": unit,
                    "price": price,
                    "message": f"⚙️ **[Local Fallback Decoded]** Adding **{qty} {unit}** of *'{p_name}'* at **₹ {price} per {unit}** to store."
                }

            # 2. Stock updates: "update tomato stock to 25kg" or "set milk stock to 10"
            stock_match = re.search(r'(?:update|set|change)\s+([\w\s]+?)\s+stock\s+to\s+(\d+(?:\.\d+)?)', msg_lower)
            if stock_match:
                p_name = stock_match.group(1).strip()
                qty = float(stock_match.group(2))
                return {
                    "action": "update_stock",
                    "product_name": p_name,
                    "quantity": qty,
                    "message": f"⚙️ **[Local Fallback Decoded]** Updating stock of *'{p_name}'* to **{qty}**."
                }

            # 3. Analytics queries
            if "today" in msg_lower and "sales" in msg_lower:
                return {"action": "reply", "message": self.execute_local_analytics(user, "today_sales")}
            if "weekly" in msg_lower or "revenue" in msg_lower:
                return {"action": "reply", "message": self.execute_local_analytics(user, "weekly_revenue")}
            if "low stock" in msg_lower or "restock" in msg_lower:
                return {"action": "reply", "message": self.execute_local_analytics(user, "low_stock")}
            if "most sold" in msg_lower or "popular" in msg_lower or "best selling" in msg_lower:
                return {"action": "reply", "message": self.execute_local_analytics(user, "most_sold")}
            if "customer" in msg_lower or "loyalty" in msg_lower or "spenders" in msg_lower:
                return {"action": "reply", "message": self.execute_local_analytics(user, "top_customers")}

            # General greeting fallback for owner
            return {
                "action": "reply",
                "message": f"👋 **Hello Boss! I am your MiniMartPro Business Intelligence assistant.**\n\n"
                           f"I'm operating in **Database-Direct mode** (AI backend key offline). I can perform database management and compile reports directly for you:\n\n"
                           f"*   🔍 *'sales today'* - today's total revenue & orders.\n"
                           f"*   📈 *'weekly revenue'* - earnings summary of last 7 days.\n"
                           f"*   ⚠️ *'low stock'* - alert listing low stock levels.\n"
                           f"*   ⭐️ *'most sold'* - top 5 products ranking.\n"
                           f"*   👑 *'top customers'* - list of VIP customer spenders.\n"
                           f"*   📦 *'Add 10kg tomato product with ₹40 per kg'* - register a product.\n"
                           f"*   ⚙️ *'Update tomato stock to 50'* - adjust inventory stock levels."
            }

        # CUSTOMER LOCAL FALLBACK
        else:
            shop_id = context_data.get("shop_id") if context_data else None
            
            # Greetings
            greetings = ["hi", "hello", "hey", "yo", "good morning", "welcome"]
            if any(g in msg_lower for g in greetings) or msg_lower in ["hi", "hello", "hey"]:
                name_pref = f" {user.username}" if user else ""
                welcome_msg = f"👋 **Welcome back{name_pref}! I am your MiniMartPro Shopping Assistant.**\n\n"
                
                if shop_id:
                    shop = db.session.get(Shop, int(shop_id))
                    if shop:
                        # Fetch shop offers and favorites if customer bought before
                        now = datetime.datetime.now()
                        offers = ShopOffer.query.filter(ShopOffer.shop_id == shop.id, ShopOffer.start_date <= now, ShopOffer.end_date >= now).all()
                        
                        welcome_msg += f"I am running in **Database-Direct mode** and am ready to shop from **\"{shop.name}\"**! Here is what's hot today:\n\n"
                        
                        if offers:
                            welcome_msg += f"🏷️ **Active Promotions Today:**\n"
                            for o in offers:
                                welcome_msg += f"*   *{o.title}* - **{o.discount_percentage}% OFF**! Coupon: `{o.coupon_code or 'N/A'}`\n"
                            welcome_msg += "\n"
                            
                        welcome_msg += f"You can add items straight to your cart. Try saying:\n" \
                                       f"*   🛒 *'add 2kg onion'* or *'buy milk'*\n" \
                                       f"*   🔍 *'do you have potatoes?'* to search the store.\n" \
                                       f"*   📄 *'show cart'* to inspect your active shopping cart."
                        return {"action": "reply", "message": welcome_msg}
                
                welcome_msg += "I am ready to help you search stores and compile baskets. Explore our **Shops list**, click into a store, and ask me to add products directly!"
                return {"action": "reply", "message": welcome_msg}

            # Cart View
            if "cart" in msg_lower or "checkout" in msg_lower or "basket" in msg_lower:
                return {
                    "action": "view_cart",
                    "message": "🛒 **Opening your cart!** Click the **Cart** link in the navigation menu to review items and complete checkout."
                }

            # Add to Cart parsing
            add_keywords = ["add", "buy", "get", "put", "order", "purchase", "want", "take"]
            is_add_intent = any(k in msg_lower for k in add_keywords) or "to cart" in msg_lower
            
            if is_add_intent and shop_id:
                # Extract quantity
                numbers = re.findall(r'\b\d+(?:\.\d+)?\b', msg_lower)
                quantity = 1.0
                if numbers:
                    try:
                        quantity = float(numbers[0])
                    except ValueError:
                        quantity = 1.0
                
                # Extract unit
                unit = "piece"
                if "kg" in msg_lower or "kilo" in msg_lower:
                    unit = "kg"
                elif "g" in msg_lower or "gram" in msg_lower:
                    unit = "g"
                elif "litre" in msg_lower or "liter" in msg_lower or "l" in msg_lower:
                    unit = "litre"
                
                # Match product name
                products = Product.query.filter_by(shop_id=shop_id).all()
                matched_p = None
                for p in products:
                    p_name = p.name.lower()
                    if p_name in msg_lower or (p_name + "s") in msg_lower or (p_name[:-1] in msg_lower if p_name.endswith('s') else False):
                        matched_p = p
                        break
                        
                if matched_p:
                    if matched_p.stock < quantity:
                        return {"action": "reply", "message": f"⚠️ Sorry, **\"{matched_p.name}\"** is low in stock. Only **{matched_p.stock}** available."}
                        
                    return {
                        "action": "add_to_cart",
                        "products": [{"product_id": matched_p.id, "quantity": quantity, "unit": unit}],
                        "message": f"✅ **Added to Cart!**\n*   {quantity} {unit} of **{matched_p.name}** (₹{matched_p.price}/{matched_p.price_unit})"
                    }
                else:
                    return {"action": "reply", "message": "🔍 I couldn't find a matching product for your request in this store. Please verify spelling or look through the shelf grids above."}

            # Search Catalog
            if shop_id:
                products = Product.query.filter_by(shop_id=shop_id).all()
                matched_p = None
                for p in products:
                    p_name = p.name.lower()
                    if p_name in msg_lower:
                        matched_p = p
                        break
                        
                if matched_p:
                    return {
                        "action": "reply",
                        "message": f"🔍 **Product Found in Stock!**\n\n"
                                   f"*   **Product Name:** {matched_p.name}\n"
                                   f"*   **Price:** ₹ {matched_p.price} per {matched_p.price_unit}\n"
                                   f"*   **Current Stock:** {matched_p.stock} remaining\n"
                                   f"*   **Description:** {matched_p.description or 'Premium quality item.'}\n\n"
                                   f"Would you like me to add it? Say: *'add {matched_p.name}'*!"
                    }

            # Default customer fallback
            if shop_id:
                all_instock = Product.query.filter(Product.shop_id == shop_id, Product.stock > 0).limit(5).all()
                if all_instock:
                    list_desc = "\n".join([f"*   **{p.name}** - ₹{p.price}/{p.price_unit}" for p in all_instock])
                    return {"action": "reply", "message": f"🤖 **I can search this store and add products to your cart.**\n\nHere are some items currently in stock in this shop:\n{list_desc}\n\nAsk me to add any of these, e.g., *'add 2 {all_instock[0].name}'*!"}

            return {"action": "reply", "message": "🤖 I am ready to assist. Please select a shop and open the chat to look up active offers, search products, or compile your shopping cart!"}

bot = Chatbot()

import os
import json
import re
from models import Product, db

# Configure Gemini AI
# The API key must be provided in the .env file.
api_key = os.environ.get("GEMINI_API_KEY", "")
SYSTEM_INSTRUCTION = """You are a helpful AI shopping assistant for MiniMartPro.
You help users find products, recommend items, and add items to their cart.
You must ALWAYS respond with a JSON object.
The JSON object must have the following structure:
{
    "action": "reply" | "view_cart" | "add_to_cart",
    "message": "Your text response to the user",
    "product_name": "Name of the product the user wants to add (only required if action is add_to_cart)",
    "quantity": <integer> (the quantity of the product to add, default to 1 if not specified. only required if action is add_to_cart)
}
Examples:
User: "Hi" -> {"action": "reply", "message": "Hello! I am your MiniMartPro AI assistant. How can I help you today?"}
User: "I want to buy 2 apples" -> {"action": "add_to_cart", "message": "Adding apples to your cart.", "product_name": "apples", "quantity": 2}
User: "Show my cart" -> {"action": "view_cart", "message": "You can view your cart by clicking the Cart link."}
User: "Do you have milk?" -> {"action": "reply", "message": "I can help you search for milk in our store. Just ask me to add it if you'd like!"}
"""

class Chatbot:
    def __init__(self):
        self.client = None
        if api_key:
            try:
                # Import only inside try to prevent crash if not installed
                from google import genai
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"Failed to initialize Gemini Client: {e}")
        
    def process_message(self, message):
        msg = message.strip()
        if not msg:
             return {"action": "reply", "message": "Please say something!"}
             
        # If the API key is not configured or client is offline, use the smart local fallback engine!
        if not self.client:
             return self.local_fallback_process(msg)
             
        try:
            from google.genai import types
            # Generate response from Gemini
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=msg,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(response.text)
            
            action = result.get("action", "reply")
            message_text = result.get("message", "I didn't quite get that.")
            
            # If the action is add_to_cart, verify against database
            if action == "add_to_cart":
                product_name = result.get("product_name", "")
                try:
                    quantity = int(result.get("quantity", 1))
                except (ValueError, TypeError):
                    quantity = 1
                
                if not product_name:
                    return {"action": "reply", "message": "What product would you like to add?"}
                    
                # Search database
                products = Product.query.filter(Product.name.ilike(f"%{product_name}%")).all()
                if not products:
                    return {"action": "reply", "message": f"I couldn't find any product matching '{product_name}'. Can you try being more specific?"}
                    
                product = products[0]
                if product.stock < quantity:
                     return {"action": "reply", "message": f"Sorry, we only have {product.stock} of '{product.name}' in stock."}
                     
                return {
                    "action": "add_to_cart",
                    "product_id": product.id,
                    "quantity": quantity,
                    "product_name": product.name,
                    "message": f"✅ I have added {quantity} x '{product.name}' to your cart!"
                }
                
            return {
                "action": action,
                "message": message_text
            }
            
        except Exception as e:
            print(f"Chatbot Gemini Error: {e}. Switching to Local Database Engine.")
            # Fall back gracefully to the local rule matching engine!
            return self.local_fallback_process(msg)

    def local_fallback_process(self, msg):
        msg_lower = msg.lower().strip()
        
        # 1. Greetings
        greetings = ["hi", "hello", "hey", "hola", "greetings", "good morning", "good afternoon", "yo", "wassup"]
        if any(g in msg_lower for g in greetings) or msg_lower in ["hi", "hello", "hey"]:
            return {
                "action": "reply",
                "message": "👋 Hello! I'm your MiniMartPro virtual assistant.\n\n"
                           "I am currently running in **Local Database Mode** (since the Gemini AI Key is currently offline or reported as leaked).\n\n"
                           "But don't worry! I can still search our catalog, look up product stock, and add items directly to your cart! "
                           "Try asking me things like:\n"
                           "* 🔍 *'Do you have apples?'* or *'search milk'* to find products.\n"
                           "* 🛒 *'Add 2 apples'* or *'buy milk'* to add them to your cart!\n"
                           "* 📄 *'Show my cart'* to open your current cart."
            }
            
        # 2. View Cart intent
        cart_intents = ["cart", "show cart", "view cart", "checkout", "basket", "my cart"]
        if any(c in msg_lower for c in cart_intents) or msg_lower == "cart":
            return {
                "action": "view_cart",
                "message": "🛒 Opening your cart! You can view and edit it by clicking the **Cart** link in the navigation bar."
            }

        # 3. Add to Cart intent
        add_keywords = ["add", "buy", "get", "put", "order", "purchase", "want", "take"]
        is_add_intent = any(k in msg_lower for k in add_keywords) or "to cart" in msg_lower
        
        # Extract quantity (first number in the query)
        numbers = re.findall(r'\b\d+(?:\.\d+)?\b', msg_lower)
        quantity = 1.0
        if numbers:
            try:
                quantity = float(numbers[0])
            except ValueError:
                quantity = 1.0
            
        # Try to find a matching product in the database
        all_products = Product.query.all()
        matched_product = None
        
        for p in all_products:
            p_name = p.name.lower()
            if p_name in msg_lower or (p_name + "s") in msg_lower or (p_name[:-1] in msg_lower if p_name.endswith('s') else False):
                matched_product = p
                break
                
        if is_add_intent and matched_product:
            if matched_product.stock < quantity:
                return {
                    "action": "reply",
                    "message": f"⚠️ Sorry, we only have **{matched_product.stock}** of *'{matched_product.name}'* in stock right now."
                }
            return {
                "action": "add_to_cart",
                "product_id": matched_product.id,
                "quantity": quantity,
                "product_name": matched_product.name,
                "message": f"✅ I have added **{quantity}** of *'{matched_product.name}'* to your cart!"
            }

        # 4. Search / "Do you have" intent
        search_keywords = ["have", "find", "search", "show", "look", "get", "do you sell", "sell", "need"]
        is_search_intent = any(sk in msg_lower for sk in search_keywords) or matched_product
        
        if is_search_intent or matched_product:
            if matched_product:
                return {
                    "action": "reply",
                    "message": f"🔍 Yes! We have *'{matched_product.name}'* in stock!\n\n"
                               f"*   **Price:** ₹ {matched_product.price} / {matched_product.price_unit}\n"
                               f"*   **Stock:** {matched_product.stock} remaining\n"
                               f"*   **Description:** {matched_product.description or 'No description available'}\n\n"
                               f"Would you like me to add it to your cart? Try saying: *'add {matched_product.name} to cart'*!"
                }
            
            # Otherwise search by matching individual words
            search_query = ""
            for word in msg_lower.split():
                if len(word) > 2 and word not in add_keywords and word not in search_keywords and word not in ["the", "for", "and", "you", "item", "please"]:
                    search_query = word
                    break
                    
            if search_query:
                products = Product.query.filter(Product.name.ilike(f"%{search_query}%")).all()
                if products:
                    reply_msg = f"🔍 I found **{len(products)}** products matching *'{search_query}'*:\n\n"
                    for p in products[:3]:
                        reply_msg += f"*   **{p.name}** - ₹ {p.price} per {p.price_unit} (Stock: {p.stock})\n"
                    reply_msg += "\nTo add any of these, just say e.g., *'add 2 {0}'*!".format(products[0].name)
                    return {"action": "reply", "message": reply_msg}

        # 5. Default Fallback
        # Explain politely and list all products currently in stock
        all_instock = Product.query.filter(Product.stock > 0).limit(5).all()
        products_list = ""
        for p in all_instock:
            products_list += f"*   **{p.name}** (₹ {p.price})\n"
            
        fallback_item = all_instock[0].name if all_instock else "milk"
        return {
            "action": "reply",
            "message": f"🤖 I am running in **Safe Database Mode** (Gemini API key is offline/leaked).\n\n"
                       f"I can still help you shop! Here are some items currently in stock:\n{products_list}\n"
                       f"Tell me what you'd like to add! For example: *'add {fallback_item}'*!"
        }

bot = Chatbot()

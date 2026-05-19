import os
import json
from models import Product, db
from google import genai
from google.genai import types

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
                self.client = genai.Client(api_key=api_key)
            except Exception as e:
                print(f"Failed to initialize Gemini Client: {e}")
        
    def process_message(self, message):
        msg = message.strip()
        if not msg:
             return {"action": "reply", "message": "Please say something!"}
             
        if not self.client:
             return {
                 "action": "reply",
                 "message": "AI assistant is currently offline. Please ask the administrator to configure the GEMINI_API_KEY in the .env file."
             }
             
        try:
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
            
        except json.JSONDecodeError:
            return {"action": "reply", "message": "I encountered an error parsing the AI response. Please try again."}
        except Exception as e:
            print(f"Chatbot Error: {e}")
            return {"action": "reply", "message": "I'm having trouble connecting to my AI brain right now. Please try again later."}

bot = Chatbot()

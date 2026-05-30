import os
from app import app, db
from models import Product

def run_migration():
    with app.app_context():
        print("================================================================")
        print("[MIGRATION LOG] Starting Product Image Audit & Repair Sweep...")
        print("================================================================")
        
        products = Product.query.all()
        print(f"[MIGRATION LOG] Total product records retrieved: {len(products)}")
        
        repaired_count = 0
        for p in products:
            original_image = p.image
            is_broken = False
            reason = ""
            
            # Case 1: Image is empty, null, or is literal "None" / "null" string
            if not p.image or p.image.strip() == "" or p.image.lower() in ("none", "null"):
                is_broken = True
                reason = "Image path is empty, null, or set to string 'None'/'null'"
            
            # Case 2: Image is a full public URL (Cloudinary or Unsplash etc.)
            elif p.image.startswith(("http://", "https://")):
                # Check for obviously broken placeholders
                if "broken" in p.image.lower() or "invalid" in p.image.lower():
                    is_broken = True
                    reason = "Image URL is flagged as invalid or broken"
            
            # Case 3: Image is a local filename
            else:
                upload_folder = app.config.get('UPLOAD_FOLDER', 'static/uploads')
                file_path = os.path.join(upload_folder, p.image)
                if not os.path.exists(file_path):
                    is_broken = True
                    reason = f"Local file '{p.image}' does not exist on disk at path: {file_path}"
            
            # Heal the broken record
            if is_broken:
                # Set to empty string so that the new image_url model property automatically serves placeholder-product.svg
                p.image = ""
                repaired_count += 1
                print(f"[REPAIR SWEEP] Product '{p.name}' (ID: {p.id}) has invalid image reference.")
                print(f"               ↳ Reason: {reason}")
                print(f"               ↳ Fix: Cleared image field in DB to trigger the dynamic placeholder fallback.")
                print("----------------------------------------------------------------")
        
        if repaired_count > 0:
            try:
                db.session.commit()
                print(f"[MIGRATION LOG] Sweep completed successfully! Repaired {repaired_count} product(s) in the database.")
            except Exception as e:
                db.session.rollback()
                print(f"[MIGRATION LOG] Critical: Failed to save migration changes to database: {str(e)}")
        else:
            print("[MIGRATION LOG] Sweep completed. All existing product records are clean and valid.")
        
        print("================================================================")

if __name__ == "__main__":
    run_migration()

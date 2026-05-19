import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
from models import db, Order, OrderItem, Product, User

class RecommenderSystem:
    def __init__(self):
        self.co_occurrence_matrix = None
        self.user_item_matrix = None
        self.user_similarity = None

    def _get_orders_df(self):
        # Fetch all orders and items
        query = db.session.query(
            Order.customer_id,
            OrderItem.order_id,
            OrderItem.product_id
        ).join(OrderItem, Order.id == OrderItem.order_id).statement
        
        df = pd.read_sql(query, db.engine)
        return df

    def train_models(self):
        df = self._get_orders_df()
        if df.empty:
            return
        
        # 1. Frequently Bought Together (Item Co-occurrence)
        # Create a boolean matrix where rows are order_id and columns are product_id
        basket = df.groupby(['order_id', 'product_id'])['product_id'].count().unstack().reset_index().fillna(0).set_index('order_id')
        basket = basket.map(lambda x: 1 if x > 0 else 0)
        
        # Item-Item co-occurrence matrix
        self.co_occurrence_matrix = basket.T.dot(basket)
        
        # 2. Collaborative Filtering (User-Item Matrix)
        user_item = df.groupby(['customer_id', 'product_id'])['product_id'].count().unstack().fillna(0)
        self.user_item_matrix = user_item.map(lambda x: 1 if x > 0 else 0)
        
        # Compute cosine similarity between users
        if len(self.user_item_matrix) > 1:
            self.user_similarity = cosine_similarity(self.user_item_matrix)
            self.user_similarity = pd.DataFrame(self.user_similarity, index=self.user_item_matrix.index, columns=self.user_item_matrix.index)

    def get_frequently_bought_together(self, product_ids, limit=4):
        """Recommend products based on items in cart/viewed (Item Association)"""
        if self.co_occurrence_matrix is None or self.co_occurrence_matrix.empty:
            return []
            
        recommendations = pd.Series(dtype=float)
        
        for pid in product_ids:
            if pid in self.co_occurrence_matrix.columns:
                recommendations = recommendations.add(self.co_occurrence_matrix[pid], fill_value=0)
                
        # Remove already selected products
        recommendations = recommendations.drop(product_ids, errors='ignore')
        
        if recommendations.empty:
            return []
            
        top_items = recommendations.sort_values(ascending=False).head(limit).index.tolist()
        return Product.query.filter(Product.id.in_(top_items)).all()

    def get_user_recommendations(self, user_id, limit=4):
        """Recommend products based on similar users (Collaborative Filtering)"""
        if self.user_similarity is None or self.user_item_matrix is None:
            return []
            
        if user_id not in self.user_similarity.index:
            return []
            
        # Get similar users
        similar_users = self.user_similarity[user_id].sort_values(ascending=False).drop(user_id, errors='ignore')
        
        if similar_users.empty:
            return []
            
        # Get products bought by similar users
        user_history = self.user_item_matrix.loc[user_id]
        unseen_products = user_history[user_history == 0].index
        
        # Weighted score based on user similarity
        product_scores = {}
        for sim_user, score in similar_users.items():
            if score <= 0: continue
            sim_user_history = self.user_item_matrix.loc[sim_user]
            for pid in unseen_products:
                if sim_user_history[pid] > 0:
                    product_scores[pid] = product_scores.get(pid, 0) + score
                    
        # Sort and return top items
        top_items = sorted(product_scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        top_product_ids = [pid for pid, score in top_items]
        
        if not top_product_ids:
            return []
            
        return Product.query.filter(Product.id.in_(top_product_ids)).all()

    def get_hybrid_recommendations(self, user_id=None, cart_product_ids=None, limit=4):
        """Combine strategies for best recommendations"""
        recommendations = set()
        
        # 1. If cart has items, prioritize frequently bought together
        if cart_product_ids:
            freq_bought = self.get_frequently_bought_together(cart_product_ids, limit=limit)
            for p in freq_bought:
                recommendations.add(p)
                
        # 2. Add user-based recommendations if needed
        if len(recommendations) < limit and user_id:
            user_recs = self.get_user_recommendations(user_id, limit=limit)
            for p in user_recs:
                if p not in recommendations and (not cart_product_ids or p.id not in cart_product_ids):
                    recommendations.add(p)
                    
        # 3. Fallback: Popular products
        if len(recommendations) < limit:
            popular = self.get_popular_products(limit)
            for p in popular:
                if p not in recommendations and (not cart_product_ids or p.id not in cart_product_ids):
                    recommendations.add(p)
                    
        return list(recommendations)[:limit]

    def get_popular_products(self, limit=4):
        """Fallback recommendation: Most ordered items"""
        df = self._get_orders_df()
        if df.empty:
            return Product.query.limit(limit).all()
            
        top_items = df['product_id'].value_counts().head(limit).index.tolist()
        return Product.query.filter(Product.id.in_(top_items)).all()

recommender = RecommenderSystem()

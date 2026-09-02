export interface Product {
  id: number;
  sku: string;
  name: string;
  brand: string;
  category: string;
  price_paise: number;
  price_display: string;
  unit: string;
  stock: number;
  description: string;
  tags: string[];
}

export interface ProductListResponse {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
}

export interface Category {
  category: string;
  product_count: number;
}

export interface CartItem {
  id: number;
  product_id: number;
  sku: string;
  name: string;
  quantity: number;
  unit_price_paise: number;
  unit_price_display: string;
  line_total_paise: number;
  line_total_display: string;
}

export interface Cart {
  id: number;
  user_id: string;
  status: string;
  created_at: string;
  items: CartItem[];
  total_paise: number;
  total_display: string;
}

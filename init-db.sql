-- ========================================================
-- PRODUCTION DATABASE SCHEMA: 24/7 FINANCIAL NEWS AGGREGATOR
-- Stack: n8n + Firecrawl + Google Gemini (LLM) + PostgreSQL
-- ========================================================

-- Kích hoạt extension tính độ tương đồng chuỗi để phát hiện trùng lặp nội dung
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Schema riêng cho n8n workflow engine
CREATE SCHEMA IF NOT EXISTS n8n;

-- Bảng lưu trữ bài viết đã cào & bóc tách thông tin
CREATE TABLE IF NOT EXISTS public.crawled_articles (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    key_points JSONB DEFAULT '[]'::jsonb,
    content_raw TEXT,
    structured_data JSONB DEFAULT '{}'::jsonb,
    source_name VARCHAR(100) NOT NULL,
    source_category VARCHAR(100) NOT NULL,
    source_url TEXT NOT NULL,
    author VARCHAR(255),
    sentiment VARCHAR(30) DEFAULT 'Neutral',
    tags TEXT[] DEFAULT '{}',
    title_hash VARCHAR(64),
    is_duplicate BOOLEAN DEFAULT FALSE,
    duplicate_of_id INT REFERENCES public.crawled_articles(id) ON DELETE SET NULL,
    status VARCHAR(50) DEFAULT 'processed',
    published_date TIMESTAMPTZ,
    crawled_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Bổ sung cột author nếu bảng đã tồn tại từ trước
ALTER TABLE public.crawled_articles ADD COLUMN IF NOT EXISTS author VARCHAR(255);
ALTER TABLE public.crawled_articles ADD COLUMN IF NOT EXISTS structured_data JSONB DEFAULT '{}'::jsonb;

-- Indexes tối ưu hóa tốc độ lọc và chống trùng lặp
CREATE INDEX IF NOT EXISTS idx_crawled_articles_url ON public.crawled_articles(url);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_source_name ON public.crawled_articles(source_name);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_source_category ON public.crawled_articles(source_category);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_crawled_at ON public.crawled_articles(crawled_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_is_duplicate ON public.crawled_articles(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_title_hash ON public.crawled_articles(title_hash);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_title_trgm ON public.crawled_articles USING gin (title gin_trgm_ops);

-- Bảng quản lý danh sách nguồn tin
CREATE TABLE IF NOT EXISTS public.crawl_targets (
    id SERIAL PRIMARY KEY,
    source_name VARCHAR(100) NOT NULL,
    source_category VARCHAR(100) NOT NULL,
    source_url TEXT UNIQUE NOT NULL,
    active BOOLEAN DEFAULT TRUE,
    crawl_frequency_minutes INT DEFAULT 30,
    last_crawled_at TIMESTAMPTZ,
    last_status VARCHAR(50) DEFAULT 'init',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Khởi tạo danh sách 16 nguồn tin mặc định nếu chưa có
INSERT INTO public.crawl_targets (source_name, source_category, source_url, crawl_frequency_minutes)
VALUES
    ('VSDC', 'Cơ quan Quản lý & Pháp lý', 'https://vsdc.vn/vi/tin-thi-truong-co-so', 30),
    ('UBCKNN', 'Cơ quan Quản lý & Pháp lý', 'https://ssc.gov.vn/webcenter/portal/ubck/pages_r/m/tintc-skin', 30),
    ('UBCKNN - Công bố', 'Cơ quan Quản lý & Pháp lý', 'https://congbothongtin.ssc.gov.vn/', 15),
    ('UBCKNN - Hồ sơ Công ty đại chúng', 'Cơ quan Quản lý & Pháp lý', 'https://congbothongtin.ssc.gov.vn/faces/CompanyProfilesSearch', 1440),
    ('UBCKNN - Tổ chức kiểm toán', 'Cơ quan Quản lý & Pháp lý', 'https://congbothongtin.ssc.gov.vn/faces/CompanyAuditingSearch', 1440),
    ('Cổng TT Chính phủ', 'Chính sách & Vĩ mô', 'https://chinhphu.vn/chinh-phu', 30),
    ('CNBC - Markets', 'Tài chính Quốc tế', 'https://www.cnbc.com/markets/', 30),
    ('CNBC - Economy', 'Tài chính Quốc tế', 'https://www.cnbc.com/economy/', 30),
    ('CNN - Business', 'Tài chính Quốc tế', 'https://edition.cnn.com/business', 30),
    ('BBC - Business', 'Tài chính Quốc tế', 'https://www.bbc.com/business', 30),
    ('CNBC', 'Tài chính Quốc tế', 'https://www.cnbc.com/', 30),
    ('FT Markets Data', 'Tài chính Quốc tế', 'https://markets.ft.com/data', 60),
    ('VnBusiness - Tài chính', 'Báo Tài chính VN', 'https://vnbusiness.vn/tai-chinh', 30),
    ('VnBusiness - Chứng khoán', 'Báo Tài chính VN', 'https://vnbusiness.vn/chung-khoan', 30),
    ('VnBusiness - Doanh nghiệp', 'Báo Tài chính VN', 'https://vnbusiness.vn/doanh-nghiep', 30),
    ('Thời báo Tài chính - Tài chính', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/tai-chinh', 30),
    ('Thời báo Tài chính - Đầu tư', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/dau-tu', 30),
    ('Thời báo Tài chính - Chứng khoán', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/chung-khoan', 30)
ON CONFLICT (source_url) DO UPDATE 
SET source_name = EXCLUDED.source_name, source_category = EXCLUDED.source_category;

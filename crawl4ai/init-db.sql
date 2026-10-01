-- ========================================================
-- PRODUCTION DATABASE SCHEMA: CRAWL4AI + N8N PIPELINE
-- ========================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Schema riêng cho n8n engine
CREATE SCHEMA IF NOT EXISTS n8n;

-- 1. Bảng lưu trữ danh sách các nguồn tin cần cào
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

-- 2. Bảng lưu trữ bài báo đã cào và chuẩn hóa
CREATE TABLE IF NOT EXISTS public.crawled_articles (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    content_raw TEXT,
    published_date TIMESTAMPTZ,
    author VARCHAR(255),
    source_name VARCHAR(100),
    source_category VARCHAR(100),
    source_url TEXT,
    tags TEXT[] DEFAULT '{}',
    sentiment VARCHAR(30) DEFAULT 'Trung lập',
    metadata JSONB DEFAULT '{}'::jsonb,
    crawled_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tạo Indexes tối ưu hóa tốc độ kiểm tra trùng lặp
CREATE INDEX IF NOT EXISTS idx_crawled_articles_url ON public.crawled_articles(url);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_source_name ON public.crawled_articles(source_name);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_crawled_at ON public.crawled_articles(crawled_at DESC);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_published_date ON public.crawled_articles(published_date DESC);
CREATE INDEX IF NOT EXISTS idx_crawled_articles_title_trgm ON public.crawled_articles USING gin (title gin_trgm_ops);

-- 4. Thêm sẵn các nguồn tin tài chính & chứng khoán mẫu
INSERT INTO public.crawl_targets (source_name, source_category, source_url, crawl_frequency_minutes)
VALUES
    ('CafeF - Chứng khoán', 'Báo Tài chính VN', 'https://cafef.vn/thi-truong-chung-khoan.chn', 30),
    ('VnEconomy - Chứng khoán', 'Báo Tài chính VN', 'https://vneconomy.vn/chung-khoan.htm', 30),
    ('VnBusiness - Chứng khoán', 'Báo Tài chính VN', 'https://vnbusiness.vn/chung-khoan', 30),
    ('VnBusiness - Tài chính', 'Báo Tài chính VN', 'https://vnbusiness.vn/tai-chinh', 30),
    ('VnBusiness - Doanh nghiệp', 'Báo Tài chính VN', 'https://vnbusiness.vn/doanh-nghiep', 30),
    ('Thời báo Tài chính - Chứng khoán', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/chung-khoan', 30),
    ('Thời báo Tài chính - Tài chính', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/tai-chinh', 30),
    ('Thời báo Tài chính - Đầu tư', 'Báo Tài chính VN', 'https://thoibaotaichinhvietnam.vn/dau-tu', 30),
    ('Cổng TT Chính phủ', 'Chính sách & Vĩ mô', 'https://chinhphu.vn/chinh-phu', 30),
    ('VSDC - Tin thị trường cơ sở', 'Cơ quan Quản lý VN', 'https://vsdc.vn/vi/tin-thi-truong-co-so', 30),
    ('UBCKNN - Tin tức thị trường', 'Cơ quan Quản lý VN', 'https://ssc.gov.vn/webcenter/portal/ubck/pages_r/m/tintc-skin', 30),
    ('UBCKNN - Cổng công bố thông tin', 'Cơ quan Quản lý VN', 'https://congbothongtin.ssc.gov.vn/', 30),
    ('CNBC - Markets', 'Tài chính Quốc tế', 'https://www.cnbc.com/markets/', 30),
    ('CNBC - Business', 'Tài chính Quốc tế', 'https://www.cnbc.com/business', 30),
    ('Bloomberg - Tech Sectors', 'Tài chính Quốc tế', 'https://www.bloomberg.com/markets/sectors/information-technology', 30),
    ('Bloomberg - Markets', 'Tài chính Quốc tế', 'https://www.bloomberg.com/markets', 30),
    ('WSJ - Business', 'Tài chính Quốc tế', 'https://www.wsj.com/business', 30),
    ('Financial Times - Companies', 'Tài chính Quốc tế', 'https://www.ft.com/companies', 30),
    ('Financial Times - Markets Data', 'Tài chính Quốc tế', 'https://markets.ft.com/data', 30)
ON CONFLICT (source_url) DO UPDATE 
SET source_name = EXCLUDED.source_name, 
    source_category = EXCLUDED.source_category,
    active = true;


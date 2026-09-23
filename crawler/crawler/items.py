import scrapy


class ArticleItem(scrapy.Item):
    source = scrapy.Field()
    source_name = scrapy.Field()
    region = scrapy.Field()
    language = scrapy.Field()
    url = scrapy.Field()
    title = scrapy.Field()
    description = scrapy.Field()
    author = scrapy.Field()
    published_at = scrapy.Field()
    content_markdown = scrapy.Field()
    content_html = scrapy.Field()
    discovery_method = scrapy.Field()
    renderer = scrapy.Field()
    discovered_at = scrapy.Field()
    raw_data = scrapy.Field()

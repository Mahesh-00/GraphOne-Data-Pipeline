from src.config import SourceConfig
from src.scrapers.directory_scraper import DirectoryScraper
from src.scrapers.base_scraper import RawDocument


def test_yc_directory_parser_extracts_company_links():
    source = SourceConfig(
        name="YCombinator", base_url="https://www.ycombinator.com/companies",
        kind="startup_directory", requires_js=True,
    )
    scraper = DirectoryScraper(source, "a[href^='/companies/']", "a", "a")
    html = '''
    <html><body>
      <a href="/companies/acme-ai">Acme AI</a>
      <a href="/companies/another-ai">Another AI</a>
      <a href="/companies/acme-ai">Acme AI</a>
      <a href="/about">About</a>
    </body></html>
    '''
    raw = RawDocument("YCombinator", source.base_url, 0.0, html, "html", {})
    rows = scraper.parse(raw)
    assert [r["raw_name"] for r in rows] == ["Acme AI", "Another AI"]
    assert rows[0]["detail_url"] == "https://www.ycombinator.com/companies/acme-ai"


def test_directory_parser_falls_back_to_text_names_when_no_links_exist():
    source = SourceConfig(
        name="Techstars",
        base_url="https://www.techstars.com/portfolio",
        kind="startup_directory",
        requires_js=False,
    )
    scraper = DirectoryScraper(source, "a[href*='/portfolio/']", "a", "a")
    html = '''
    <html><body>
      <main>
        <h1>Techstars Portfolio</h1>
        <div>Alloy</div>
        <div>Identity risk and compliance for banks and fintechs.</div>
        <div>Chainalysis</div>
        <div>The investigation and compliance software the crypto economy trusts.</div>
        <div>DigitalOcean</div>
      </main>
    </body></html>
    '''
    raw = RawDocument("Techstars", source.base_url, 0.0, html, "html", {})
    rows = scraper.parse(raw)
    assert [r["raw_name"] for r in rows[:3]] == ["Alloy", "Chainalysis", "DigitalOcean"]
    assert all(r["detail_url"] == source.base_url for r in rows[:3])


def test_product_parser_skips_cloudflare_challenge_page():
    source = SourceConfig(
        name="ProductHunt",
        base_url="https://www.producthunt.com/topics/artificial-intelligence",
        kind="product_directory",
        requires_js=True,
        list_selector="a[href*='/topics/'], a[href*='/products/']",
        name_selector="a",
        link_selector="a",
    )
    scraper = DirectoryScraper(source, source.list_selector, source.name_selector, source.link_selector)
    html = '''
    <html><head><title>Just a moment...</title></head>
    <body><div>Checking your browser before accessing Product Hunt.</div></body>
    </html>
    '''
    raw = RawDocument("ProductHunt", source.base_url, 0.0, html, "html", {})
    assert scraper.parse(raw) == []


def test_there_is_an_ai_for_that_parser_filters_navigation_and_keeps_ai_tools():
    source = SourceConfig(
        name="ThereIsAnAIForThat",
        base_url="https://theresanaiforthat.com",
        kind="product_directory",
        requires_js=True,
        list_selector="a[href*='/ai/'], a[href*='/tools/']",
        name_selector="a[href*='/ai/']",
        link_selector="a[href*='/ai/']",
    )
    scraper = DirectoryScraper(source, source.list_selector, source.name_selector, source.link_selector)
    html = '''
    <html><body>
      <a href="https://theresanaiforthat.com/">Home</a>
      <a href="https://theresanaiforthat.com/?page=1">Search</a>
      <a href="https://theresanaiforthat.com/ai/ezimagetool/">EzImageTool</a>
      <a href="https://theresanaiforthat.com/ai/chatgpt/">ChatGPT</a>
      <a href="https://theresanaiforthat.com/ai/ezimagetool/">AI removes watermarks and rebuilds the detail underneath. First one free.</a>
      <a href="https://theresanaiforthat.com/?page=1">Click here to join for free!</a>
      <a href="https://theresanaiforthat.com/ai/not-about/">Sign up</a>
    </body></html>
    '''
    raw = RawDocument("ThereIsAnAIForThat", "https://theresanaiforthat.com/?page=1", 0.0, html, "html", {})
    rows = scraper.parse(raw)
    assert [r["raw_name"] for r in rows] == ["EzImageTool", "ChatGPT"]
    assert all("/ai/" in r["detail_url"] for r in rows)
    assert all(r["_source_url"] == "https://theresanaiforthat.com/?page=1" for r in rows)

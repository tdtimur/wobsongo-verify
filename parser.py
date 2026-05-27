from liteparse import LiteParse

parser = LiteParse()
result = parser.parse("static/pdfs/who-infertility-guide.pdf")
print(result.text)

# Access structured data
for page in result.pages:
    print(f"Page {page.page_num}: {len(page.text_items)} text items")

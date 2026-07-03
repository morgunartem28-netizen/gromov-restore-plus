import re
import urllib.request

EXTRA_SLUGS = [
    "gazprombank-na-iphone-cifrovoj-sejf",
    "bankovskie-prilozheniya-iphone",
]

base = "https://procash.app/articles/"
category_html = urllib.request.urlopen(
    "https://procash.app/articles/category/prilozheniya-bankov", timeout=15
).read().decode("utf-8", "replace")
slugs = sorted(set(re.findall(r"/articles/([a-z0-9-]+)", category_html)) | set(EXTRA_SLUGS))
for slug in slugs:
    if slug.startswith("category"):
        continue
    try:
        html = urllib.request.urlopen(base + slug, timeout=15).read().decode("utf-8", "replace")
        links = [
            link
            for link in sorted(set(re.findall(r"https?://apps\.apple\.com[^\"'\s<>]+", html)))
            if "pro%D0%BA%D1%8D%D1%88" not in link and "proкэш" not in link.lower()
        ]
        if not links:
            continue
        print("===", slug)
        for link in links:
            print(" ", link)
    except Exception as exc:
        print("===", slug, "ERR", exc)

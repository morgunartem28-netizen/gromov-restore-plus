import re
import urllib.request

urls = [
    "https://www.comss.ru/page.php?id=18775",
    "https://procash.app/articles/sber-finansy-onlayn-iphone",
    "https://procash.app/articles/finansy-onlayn-sber-iphone",
]
for url in urls:
    try:
        html = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")
        links = re.findall(r"https?://apps\.apple\.com[^\"'\s<>]+", html)
        print(url, links[:3])
    except Exception as exc:
        print(url, "ERR", exc)

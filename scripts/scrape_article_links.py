import re
import urllib.request

urls = [
    "https://www.nn.ru/text/economics/2024/02/01/73185626/",
    "https://itzine.ru/news/apps/sber-vypustil-novoe-prilozhenie-dlya-ios-pod-nazvaniem-finansy-onlajn-v-app-store.html",
    "https://appleinsider.ru/obzory-prilozhenij/kak-ustanovit-sberbank-onlajn-na-iphone-prilozhenie-semejnyj-onlajn-v-app-store.html",
]
for url in urls:
    html = urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")
    links = sorted(set(re.findall(r"https?://apps\.apple\.com[^\"'\s<>]+", html)))
    ids = sorted(set(re.findall(r"/id(\d{9,10})", html)))
    print("===", url)
    print("links:", links[:5])
    print("ids:", ids)

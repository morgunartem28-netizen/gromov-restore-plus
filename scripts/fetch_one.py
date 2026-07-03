import re
import sys
import urllib.request

slug = sys.argv[1]
html = urllib.request.urlopen(
    f"https://procash.app/articles/{slug}", timeout=20
).read().decode("utf-8", "replace")
links = [
    link
    for link in sorted(set(re.findall(r"https?://apps\.apple\.com[^\"'\s<>]+", html)))
    if "6752288154" not in link
]
print(slug)
for link in links:
    print(link)

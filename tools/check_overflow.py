"""Headless check: does the HUD ever produce a horizontal scrollbar?

Loads the live server at several widths, measures documentElement.scrollWidth vs
clientWidth, and lists any element whose box extends past the viewport's right
edge (the real cause of a horizontal scrollbar). Also exercises the logs drawer
and settings modal, which render variable-length content. Exits non-zero if any
width overflows. Not part of the app — a dev verification tool.
"""
import sys
from playwright.sync_api import sync_playwright

URL = "http://localhost:8765/"
WIDTHS = [360, 414, 768, 1024, 1440]

PROBE = """() => {
  const de = document.documentElement;
  const vw = de.clientWidth;
  const offenders = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    // ignore intentionally off-screen/hidden
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    if (r.right > vw + 1) {
      offenders.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && el.className.toString().slice(0, 40)) || '',
        right: Math.round(r.right), w: Math.round(r.width),
      });
    }
  }
  return { scrollW: de.scrollWidth, clientW: vw, bodyScrollW: document.body.scrollWidth,
           offenders: offenders.slice(0, 12) };
}"""


def measure(page, label):
    page.wait_for_timeout(400)
    res = page.evaluate(PROBE)
    overflow = res["scrollW"] - res["clientW"]
    status = "OK" if overflow <= 1 else f"OVERFLOW +{overflow}px"
    print(f"  [{label}] client={res['clientW']} scroll={res['scrollW']} -> {status}")
    for o in res["offenders"]:
        print(f"      ↳ <{o['tag']} class='{o['cls']}'> right={o['right']} w={o['w']}")
    return overflow <= 1


def main():
    ok = True
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w in WIDTHS:
            page = browser.new_page(viewport={"width": w, "height": 900})
            page.goto(URL, wait_until="networkidle")
            print(f"width {w}px:")
            ok &= measure(page, "base")
            # open the logs drawer (variable-length JSON rows)
            page.click("#navLogs");
            ok &= measure(page, "logs open")
            # open settings modal (full editor)
            page.click("#navSettings")
            ok &= measure(page, "settings open")
            if w == 414:
                page.screenshot(path="tools/_overflow_414.png", full_page=True)
            page.close()
        browser.close()
    print("\nRESULT:", "no horizontal scroll at any width ✅" if ok else "horizontal overflow remains ❌")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

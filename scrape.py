"""로브로브 플랫폼별 판매가를 읽어 lovlov_prices.csv 를 갱신한다 (GitHub Actions 에서 실행)."""
import csv, re, sys, time, datetime, collections, urllib.parse, difflib
from playwright.sync_api import sync_playwright

PLAT = {
    '29CM': 'https://www.29cm.co.kr/store/brand/1572',
    '무신사': 'https://www.musinsa.com/brand/lovlov',
    'W컨셉': 'https://display.wconcept.co.kr/rn/brand/102415',
    '퀸잇': 'https://web.queenit.kr/brand/LOVLOV_SEOUL',
    '지그재그': 'https://zigzag.kr/lovlovseoul',
    'SSF': 'https://www.ssfshop.com/LOVLOV/main?brandShopNo=BDMA19BBY&brndShopId=RTLVL',
    '롯데온': 'https://www.lotteon.com/p/display/seller/sellerShop/LO10167238',
}
ALIAS = {
 '이지스웻ss':'이지스웻','이지조거ss':'이지조거',
 'mysignatureknit':'마이시그니처니트','snowbloomzip-up':'스노우블룸집업','newlovwidedenim':'뉴로브와이드데님',
 'neworiginalstraightdenim':'뉴오리지널스트레이트데님','double-sidedlongmustang':'더블사이디드롱무스탕',
 '더블사이드롱무스탕':'더블사이디드롱무스탕','firstmomentminidress':'퍼스트모먼트미니드레스',
 'two-wayshirringdress':'투웨이셔링드레스','gainsbourgshearlingmustangvest':'갱스부르시어링무스탕베스트',
 'easywarmbalaclava':'이지웜바라클라바','easyformalpants':'이지포멀팬츠','finewoolstringknit':'파인울스트링니트',
 'coolstripet-shirt':'쿨스트라이프티셔츠','bemminebeart-shirts':'비마인베어티셔츠',
 '포그니딥브이넥니트':'포그니딥브이니트','빈티지크랙페이크레더봄버':'빈티지크랙레더봄버',
}
BAD = re.compile(r'2PACK|1\+1|세트|SET|묶음|골라보는|창고', re.I)
PCT = re.compile(r'^\d{1,2}%$')
NUM = re.compile(r'^[\d,]+원?~?$')
DISC = {}  # (읽은 상품명, 판매가) -> 할인율(%)
SKIP_NAME = re.compile(r'^(LOVLOV|로브로브|오늘출발|더블유위크|쿠폰|단독|무료배송|BEST|NEW|SOLD OUT|품절)$', re.I)


def clean(n):
    ss = bool(re.search(r'S\s*/\s*S\s*ver|\bSS\s*ver|\(\s*SS\s*\)', n, re.I))
    n = re.sub(r'\[[^\]]*\]', ' ', n)
    n = re.sub(r'\([^)]*\)', ' ', n)
    n = re.sub(r'_.*$', '', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n + ' SS' if ss else n


def key(n):
    k = re.sub(r'\s+', '', n).lower()
    return ALIAS.get(k, k)


def parse(text, need_brand=False):
    """innerText 에서 (상품명, 판매가) 목록을 뽑는다. 패턴: 상품명 → (원가) → NN% → 판매가."""
    L = [s.strip() for s in text.split('\n') if s.strip()]
    out = []
    for i, s in enumerate(L):
        if not PCT.match(s) or i + 1 >= len(L) or not NUM.match(L[i + 1]):
            continue
        price = int(re.sub(r'[^\d]', '', L[i + 1]))
        j = i - 1
        while j >= 0 and (NUM.match(L[j]) or PCT.match(L[j])):
            j -= 1
        if j < 0:
            continue
        name = L[j]
        if SKIP_NAME.match(name) or len(name) < 2 or len(name) > 120:
            continue
        if need_brand and not (j > 0 and L[j - 1] == '로브로브'):
            continue
        DISC[(name, price)] = int(s[:-1])
        out.append((name, price))
    return out


def collect(page, url, need_brand=False, scroll_s=45, expect_scroll=True):
    acc = {}
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(3500)
    t0 = time.time(); last = -1; stable = 0
    while time.time() - t0 < scroll_s:
        for n, p in parse(page.inner_text('body'), need_brand):
            if n not in acc or p < acc[n]:
                acc[n] = p
        if not expect_scroll:
            break
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(600)
        if len(acc) == last:
            stable += 1
            if stable > 10:
                break
        else:
            stable, last = 0, len(acc)
    return acc


def scrape_all():
    res = {}
    with sync_playwright() as pw:
        br = pw.chromium.launch()
        ctx = br.new_context(locale='ko-KR', viewport={'width': 1280, 'height': 900},
                             user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')
        page = ctx.new_page()
        jobs = {
            '29CM': lambda: pages_29cm(page),
            '무신사': lambda: {},  # GitHub 서버에서는 쿠폰 반영가가 보여 정확하지 않아 읽지 않는다
            'W컨셉': lambda: collect(page, 'https://display.wconcept.co.kr/search?keyword=%EB%A1%9C%EB%B8%8C%EB%A1%9C%EB%B8%8C&type=direct', need_brand=True, scroll_s=60),
            '퀸잇': lambda: {},  # 사용자 PC의 Chrome으로 하루 3번 읽어 manual_prices.csv 로 올린다
            '지그재그': lambda: collect(page, 'https://zigzag.kr/lovlovseoul/search?keyword=%EB%A1%9C%EB%B8%8C%EB%A1%9C%EB%B8%8C', need_brand=True, scroll_s=60),
            'SSF': lambda: {},
            '롯데온': lambda: {},
        }
        for name, fn in jobs.items():
            try:
                res[name] = fn()
            except Exception as e:  # 한 곳이 실패해도 계속한다
                print('FAIL', name, repr(e)[:200])
                res[name] = {}
            print(name, len(res[name]))
        load_manual(res)
        try:
            wconcept_fill(page, res)
        except Exception as e:
            print('FAIL wconcept_fill', repr(e)[:200])
        br.close()
    return res


MANUAL = ('무신사', '퀸잇', 'SSF', '롯데온')


def load_manual(res):
    """GitHub 서버에서 못 읽는 플랫폼은 manual_prices.csv(platform,name,price,discount)에서 가져온다."""
    try:
        rows = list(csv.DictReader(open('manual_prices.csv', encoding='utf-8')))
    except FileNotFoundError:
        print('manual_prices.csv 없음')
        return
    n = 0
    for r in rows:
        pn = r.get('platform')
        if pn not in MANUAL:
            continue
        try:
            price = int(r['price'])
        except (ValueError, KeyError):
            continue
        name = r['name'].strip()
        d = res.setdefault(pn, {})
        if name not in d or price < d[name]:
            d[name] = price
            if (r.get('discount') or '').isdigit():
                DISC[(name, price)] = int(r['discount'])
        n += 1
    print('manual rows', n, {p: len(res.get(p, {})) for p in MANUAL})


def wconcept_fill(page, res):
    """W컨셉 목록 검색에 안 잡힌 상품을, 다른 플랫폼에서 읽은 이름으로 하나씩 검색해 채운다."""
    wc = res.get('W컨셉', {})
    if len(wc) < 15:
        return
    have = {key(clean(n)) for n in wc if not BAD.search(n)}
    want = {}
    for pn, items in res.items():
        if pn == 'W컨셉':
            continue
        for raw in items:
            if BAD.search(raw):
                continue
            d = clean(raw)
            if not d or not re.search(r'[가-힣]', d):
                continue
            k = key(d)
            if k not in have and k not in want:
                want[k] = d
    added = 0
    for k, d in want.items():
        try:
            url = 'https://display.wconcept.co.kr/search?keyword=' + urllib.parse.quote('로브로브 ' + d) + '&type=direct'
            page.goto(url, wait_until='domcontentloaded', timeout=45000)
            best = None
            for _ in range(10):
                page.wait_for_timeout(1000)
                txt = page.inner_text('body')
                for n, p in parse(txt, need_brand=True):
                    if not BAD.search(n) and key(clean(n)) == k and (best is None or p < best[1]):
                        best = (n, p)
                if best or ('상품정보' in txt and _ >= 6):
                    break
            if best:
                wc[best[0]] = best[1]
                added += 1
        except Exception as e:
            print('wconcept fill fail', k, repr(e)[:80])
    print('W컨셉 fill', added, '/', len(want))


def pages_musinsa(page):
    """목록 가격은 첫구매/쿠폰이 반영된 가격이라, 상품 상세 페이지의 비로그인 판매가를 읽는다."""
    page.goto('https://www.musinsa.com/brand/lovlov?gf=A', wait_until='domcontentloaded', timeout=60000)
    page.wait_for_timeout(3500)
    ids = []
    t0 = time.time(); stable = 0
    while time.time() - t0 < 60:
        found = page.eval_on_selector_all('a[href*="/products/"]', 'els => els.map(e => e.href)')
        for h in found:
            m = re.search(r'/products/(\d+)', h)
            if m and m.group(1) not in ids:
                ids.append(m.group(1)); stable = 0
        stable += 1
        if stable > 10:
            break
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(600)
    acc = {}
    master, var = {}, {}  # 묶음(Ncolor) 상품 가격을 우선, 색상별 상품은 보조
    for pid in ids[:150]:
        try:
            page.goto(f'https://www.musinsa.com/products/{pid}', wait_until='domcontentloaded', timeout=45000)
            page.wait_for_timeout(1500)
            title = page.title()
            if '로브로브' not in title:
                continue
            name = re.sub(r'^로브로브\(LOVLOV\)\s*', '', title)
            name = re.split(r'\s+-\s+사이즈', name)[0].strip()
            body = page.inner_text('body')
            m = re.search(r'(\d{1,2})%\s*\n\s*([\d,]{4,})원', body)
            if not m or not name or SKIP_NAME.match(name):
                continue
            price = int(m.group(2).replace(',', ''))
            DISC[(name, price)] = int(m.group(1))
            print('MUSINSA', pid, name, price, m.group(1), flush=True)
            base = clean(name)
            tgt = master if re.search(r'\(\s*\d+\s*color', name, re.I) else var
            if base not in tgt or price < tgt[base][1]:
                tgt[base] = (name, price)
        except Exception as e:
            print('musinsa item fail', pid, repr(e)[:80])
    for base in set(master) | set(var):
        nm, pr = master.get(base) or var[base]
        acc[nm] = pr
    return acc


def pages_29cm(page):
    acc = {}
    for n in range(1, 9):
        got = collect(page, f'https://www.29cm.co.kr/store/brand/1572?brandId=1572&page={n}', scroll_s=8, expect_scroll=False)
        if not got:
            break
        for k, v in got.items():
            if k not in acc or v < acc[k]:
                acc[k] = v
    return acc


def pages_ssf(page):
    acc = {}
    base = 'https://www.ssfshop.com/LOVLOV/main?dspCtgryNo=SFM&brandShopNo=BDMA19BBY&brndShopId=RTLVL&sortColumn=NEW_GOD_SEQ&serviceType=DSP&ctgrySectCd=GNRL_CTGRY&fitPsbYn=N&subBrndCtgryGodYn=Y&currentPage='
    for n in range(1, 8):
        got = collect(page, base + str(n), scroll_s=25)
        if not got:
            break
        for k, v in got.items():
            if k not in acc or v < acc[k]:
                acc[k] = v
    return acc


def main():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y-%m-%dT%H:%M:00+09:00')
    old = collections.defaultdict(list)  # platform -> rows(dict)
    try:
        for r in csv.DictReader(open('lovlov_prices.csv', encoding='utf-8')):
            old[r['platform']].append(r)
    except FileNotFoundError:
        pass
    res = scrape_all()
    data = collections.defaultdict(dict)   # key -> platform -> price
    disc = collections.defaultdict(dict)   # key -> platform -> 할인율
    names = collections.defaultdict(collections.Counter)
    ok = []
    for pn, items in res.items():
        # 읽은 개수가 너무 적으면(차단·구조 변경) 그 플랫폼은 이전 값을 유지한다
        prev = len(old.get(pn, []))
        if len(items) < 15:
            print('KEEP OLD', pn, len(items), 'prev', prev)
            if pn == '무신사':
                continue  # 부정확한 이전 값은 버린다
            for r in old.get(pn, []):
                data[r['product_key']][pn] = int(r['price'])
                disc[r['product_key']][pn] = r.get('discount') or ''
                names[r['product_key']][r['name']] += 1
            continue
        ok.append(pn)
        for raw, price in items.items():
            if BAD.search(raw):
                continue
            d = clean(raw)
            if not d:
                continue
            k = key(d)
            if pn not in data[k] or price < data[k][pn]:
                data[k][pn] = price
                disc[k][pn] = DISC.get((raw, price), '')
            if re.search(r'[가-힣]', d):
                names[k][d] += 1
    # 유사 상품명 합치기: 같은 플랫폼에 겹치지 않고 이름이 매우 비슷하면 같은 상품으로 본다
    order = sorted(data, key=lambda x: -len(data[x]))
    kept = []
    for b in order:
        best, br = None, 0.0
        for a_ in kept:
            if set(data[a_]) & set(data[b]) or a_.endswith('ss') != b.endswith('ss'):
                continue
            r = difflib.SequenceMatcher(None, a_, b).ratio()
            if r >= 0.86 and r > br:
                best, br = a_, r
        if best:
            print('FUZZY MERGE', b, '->', best, round(br, 2))
            data[best].update(data[b]); disc[best].update(disc.get(b, {}))
            names[best].update(names[b]); del data[b]
        else:
            kept.append(b)
    rows = []
    for k, pp in data.items():
        if len(pp) < 2:
            continue
        nm = names[k].most_common(1)[0][0] if names[k] else k
        for pn, price in pp.items():
            rows.append(dict(product_key=k, name=nm, platform=pn, price=price, discount=disc[k].get(pn, ''), shop_url=PLAT[pn], fetched_at=now))
    plats = {r['platform'] for r in rows}
    print('products', len({r['product_key'] for r in rows}), 'rows', len(rows), 'platforms', len(plats), 'fresh', ok)
    if len(rows) < 200 or len(plats) < 5 or len(ok) < 3:
        print('too little data, not writing'); sys.exit(1)
    with open('lovlov_prices.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['product_key', 'name', 'platform', 'price', 'discount', 'shop_url', 'fetched_at'])
        w.writeheader(); w.writerows(rows)


if __name__ == '__main__':
    main()

"""Collect source leads for human review. This command is separate from app search."""
import argparse
import csv
from datetime import date
from html.parser import HTMLParser
import json
import ipaddress
from io import BytesIO
import socket
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

AGENT = 'VirtueReferralResearch'
SERVICE = {
    'mri': r'\bmri\b|magnetic resonance',
    'dialysis': r'\b(?:ha?emo)?dialysis\b',
    'c_section': r'caesarean|cesarean|c-section|emergency obstetric',
    'nicu': r'\bnicu\b|neonatal intensive care',
    'cardiac_surgery': r'cardiac surgery|heart surgery|cardiothoracic|\bcabg\b',
    'burn_care': r'burns? (?:unit|care|centre|center)',
    'trauma_care': r'trauma (?:unit|care|centre|center|team)',
}
GOVERNMENT = {'hospital_directory','public_facilities','blood_banks','pmjay','pmndp','obstetric_fru','nabh'}


def public_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Expected a public HTTP(S) source')
    if parsed.port not in (None, 80, 443):
        raise ValueError('Expected a public web port')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(entry[4][0]).is_global for entry in addresses):
        raise ValueError('Expected a public internet host')
    return parsed


class PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        old, new = public_url(request.full_url), public_url(newurl)
        if old.hostname != new.hostname:
            raise ValueError('Cross-host redirects require a separately reviewed URL')
        return super().redirect_request(request,fp,code,message,headers,newurl)


def request(url, headers=None, body=None, cap=2_000_000):
    public_url(url)
    request_headers = {'User-Agent': AGENT, **(headers or {})}
    with build_opener(PublicRedirects()).open(Request(url, headers=request_headers, data=body), timeout=18) as response:
        data = response.read(cap + 1)
        if len(data) > cap:
            raise ValueError('Source response exceeds the byte limit')
        return data, response.geturl()


def allowed_by_robots(url):
    robots_url = urljoin(url, '/robots.txt')
    rules = RobotFileParser(robots_url)
    content, _ = request(robots_url, cap=250_000)
    rules.parse(content.decode('utf-8','replace').splitlines())
    if not rules.can_fetch(AGENT,url):
        raise ValueError('robots.txt disallows the requested path')
    return rules


def record(source_type, publisher, url, **fields):
    return {'source_type': source_type, 'publisher': publisher, 'url': url,
            'checked': date.today().isoformat(), 'review_status': 'lead', **fields}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        url = dict(attrs).get('href')
        if tag == 'a' and url:
            self.links.append(url)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.hidden:
            self.hidden -= 1

    def handle_data(self, text):
        if not self.hidden and text.strip():
            self.parts.append(text.strip())


def website_leads(args):
    for row in seeds(args.input, args.limit):
        home = row['website'].strip()
        if not home:
            continue
        if not re.match(r'^https?://',home):
            home = 'https://' + home
        try:
            host = urlsplit(home).hostname
            if not host or '.' not in host:
                continue
            try:
                rules = allowed_by_robots(home)
            except Exception as error:
                print(f'Skipped {host}: could not read robots.txt ({type(error).__name__})', file=sys.stderr)
                continue
            delay = max(1, rules.crawl_delay(AGENT) or rules.crawl_delay('*') or 1)
            queue = [home]
            seen = set()
            while queue and len(seen) <= args.pages:
                url = queue.pop(0)
                if url in seen or not rules.can_fetch(AGENT, url):
                    continue
                seen.add(url)
                time.sleep(delay)
                page_body, final = request(url)
                if urlsplit(final).hostname != host:
                    continue
                page = Page()
                page.feed(page_body.decode('utf-8', 'replace'))
                if url == home:
                    candidates = (urljoin(final, link).split('#')[0] for link in page.links)
                    queue.extend(link for link in candidates if urlsplit(link).hostname == host and
                                 re.search(r'service|specialt|department|radiolog|dialysis|trauma|obstet|cardiac|nicu|burn', link, re.I))
                text = ' '.join(page.parts)
                for service, pattern in SERVICE.items():
                    hit = re.search(pattern, text, re.I)
                    if hit:
                        yield record('hospital_website', row['name'], final, facility_id=row['facility_id'],
                                     service=service, excerpt=text[max(0,hit.start()-65):hit.end()+100],
                                     rationale='Keyword excerpt from the supplied official website. Confirm service, context and campus.')
        except Exception as error:
            print(f'Skipped source for {row.get("facility_id", "")} ({type(error).__name__})', file=sys.stderr)


def source_leads(args):
    """Fetch exact demo sources with the same public-host and robots checks as crawl."""
    next_request = {}
    for row in seeds(args.input, args.limit):
        url = row['url'].strip()
        try:
            host = public_url(url).hostname
            time.sleep(max(0, next_request.get(host, 0) - time.monotonic()))
            rules = allowed_by_robots(url)
            delay = max(1, rules.crawl_delay(AGENT) or rules.crawl_delay('*') or 1)
            next_request[host] = time.monotonic() + delay
            time.sleep(delay)
            # The KEM annual report is around 52 MB. Permit larger responses only
            # for an explicitly listed PDF while keeping the read bounded.
            cap = 64_000_000 if urlsplit(url).path.lower().endswith('.pdf') else 2_000_000
            body, final = request(url, cap=cap)
            next_request[host] = time.monotonic() + delay
            if not rules.can_fetch(AGENT, final):
                raise ValueError('Final path is disallowed by robots.txt')
            if body.startswith(b'%PDF'):
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(body))
                page = int(row['page']) if row.get('page') else None
                pages = [reader.pages[page - 1]] if page else reader.pages[:40]
                text = ' '.join(item.extract_text() or '' for item in pages)
            else:
                page = Page()
                page.feed(body.decode('utf-8', 'replace'))
                text = ' '.join(page.parts)
            text = ' '.join(text.split())
            hit = re.search(row['pattern'], text, re.I)
            if not hit:
                print(f'No matching text: {url}', file=sys.stderr)
                continue
            yield record(row['source_type'], row['publisher'], final,
                         facility_id=row.get('facility_id') or None, service=row.get('service') or None,
                         name=row.get('name') or None,
                         excerpt=text[max(0, hit.start() - 60):hit.end() + 160],
                         rationale='Extracted from the source. Review exact campus, date and scope before use.')
        except (OSError, ValueError, ImportError, IndexError) as error:
            print(f'Skipped {url}: {error}', file=sys.stderr)


def tabular_leads(args):
    mapping = json.loads(Path(args.columns).read_text())
    source = args.input
    if source.startswith(('https://','http://')):
        allowed_by_robots(source)
        data, final_url = request(source,cap=35_000_000)
        if urlsplit(final_url).path.lower().endswith('.csv') or args.format == 'csv':
            rows = list(csv.DictReader(data.decode('utf-8-sig').splitlines()))
        else:
            from io import StringIO
            import pandas as pd
            rows = pd.read_html(StringIO(data.decode('utf-8','replace')),keep_default_na=False)[args.table].to_dict('records')
    elif source.lower().endswith(('.html', '.htm')) or args.format == 'html':
        import pandas as pd
        rows = pd.read_html(args.input, keep_default_na=False)[args.table].to_dict('records')
    else:
        with open(args.input, encoding='utf-8-sig', newline='') as infile:
            rows = list(csv.DictReader(infile))
    for row in rows:
        fields = {field: str(row[column]).strip() for field, column in mapping.items()
                  if field in {'facility_id','name','place','address','pin','phone','latitude','longitude','excerpt','event','published'}
                  and column in row and str(row[column]).strip()}
        if fields.get('name') or fields.get('facility_id'):
            yield record(args.source_type,args.publisher,args.url,**fields,
                         rationale='Directory, registry, or review lead. Confirm the exact campus and scope before use.')


def map_leads(args):
    with open(args.input, encoding='utf-8') as infile:
        features = json.load(infile)['features']
    for feature in features:
        geom = feature.get('geometry') or {}
        if geom.get('type') != 'Point':
            continue
        tags = feature.get('properties') or {}
        names = tags.get('names') or {}
        name = tags.get('name') or names.get('primary')
        if not name:
            continue
        lon, lat = geom['coordinates'][:2]
        yield record(args.provider,args.provider,args.url,name=name,longitude=lon,latitude=lat,
                     map_id=feature.get('id') or tags.get('id'), operating_status=tags.get('operating_status'),
                     existence_confidence=tags.get('confidence'), attribution=tags.get('sources'),
                     rationale='Map-place signal. Operating status and existence confidence describe the place, not its services or slots.')


def seeds(filename, limit):
    from itertools import islice
    with open(filename, encoding='utf-8-sig', newline='') as infile:
        yield from islice(csv.DictReader(infile),limit)


def brave_leads(args):
    key = os.environ['BRAVE_SEARCH_API_KEY']
    for row in seeds(args.input,args.limit):
        for topic in ('news','tender procurement','job vacancies'):
            terms = ' '.join([row['name'],row.get('place',''),args.service.replace('_',' '),topic])
            url = 'https://api.search.brave.com/res/v1/web/search?' + urlencode({'q':terms,'count':3})
            body,_ = request(url, {'Accept':'application/json','X-Subscription-Token':key})
            for hit in (json.loads(body).get('web') or {}).get('results',[]):
                yield record('web_search','Brave Search',hit['url'],facility_id=row['facility_id'],service=args.service,
                             excerpt=hit.get('title',''), rationale=f'{topic} discovery result. Read and cite the original source directly.')
            time.sleep(1)


def google_places(args):
    key = os.environ['GOOGLE_PLACES_API_KEY']
    for row in seeds(args.input,args.limit):
        body = json.dumps({'textQuery':row['name']+' '+row.get('address','')+' India'}).encode()
        raw,_ = request('https://places.googleapis.com/v1/places:searchText',
                        {'Content-Type':'application/json','X-Goog-Api-Key':key,
                         'X-Goog-FieldMask':'places.id'},body)
        ids = [p['id'] for p in json.loads(raw).get('places',[])]
        # IDs are durable; fetch and review business status in Google Maps itself.
        yield {'facility_id':row['facility_id'],'google_place_ids':ids,
               'maps_links':['https://www.google.com/maps/search/?api=1&'+urlencode({'query':row['name'],'query_place_id':i}) for i in ids]}


def google_status(args):
    key = os.environ['GOOGLE_PLACES_API_KEY']
    if not re.fullmatch(r'[A-Za-z0-9_-]+',args.place_id):
        raise ValueError('Expected a Google Place ID')
    raw,_ = request('https://places.googleapis.com/v1/places/'+args.place_id,
                    {'X-Goog-Api-Key':key,'X-Goog-FieldMask':'id,businessStatus,googleMapsUri,attributions'})
    place = json.loads(raw)
    # Operator-only, ephemeral display. Never insert Places content into the serving table.
    print('Google Maps · ' + str(place.get('businessStatus','Unknown')),file=sys.stderr)
    print(place.get('googleMapsUri',''),file=sys.stderr)
    for credit in place.get('attributions',[]):
        print(credit.get('provider','')+' '+credit.get('providerUri',''),file=sys.stderr)
    return ()


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('Must be positive')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    modes=parser.add_subparsers(required=True)
    crawl=modes.add_parser('crawl')
    crawl.add_argument('input')
    crawl.add_argument('--limit', type=positive, required=True)
    crawl.add_argument('--pages', type=int, choices=range(0,11),default=10)
    crawl.set_defaults(run=website_leads)
    sources=modes.add_parser('sources')
    sources.add_argument('input')
    sources.add_argument('--limit',type=positive,default=10)
    sources.set_defaults(run=source_leads)
    tab=modes.add_parser('directory')
    tab.add_argument('input')
    tab.add_argument('--source-type',choices=sorted(GOVERNMENT|{'review'}),required=True)
    tab.add_argument('--publisher',required=True)
    tab.add_argument('--url',required=True)
    tab.add_argument('--columns',required=True)
    tab.add_argument('--table',type=int,default=0)
    tab.add_argument('--format',choices=['auto','csv','html'],default='auto')
    tab.set_defaults(run=tabular_leads)
    maps=modes.add_parser('open-maps')
    maps.add_argument('input')
    maps.add_argument('--provider',choices=['OpenStreetMap','Overture'],required=True)
    maps.add_argument('--url',required=True)
    maps.set_defaults(run=map_leads)
    brave=modes.add_parser('brave')
    brave.add_argument('input')
    brave.add_argument('--limit',type=positive,required=True)
    brave.add_argument('--service',choices=SERVICE,required=True)
    brave.set_defaults(run=brave_leads)
    google=modes.add_parser('google-places')
    google.add_argument('input')
    google.add_argument('--limit',type=positive,required=True)
    google.set_defaults(run=google_places)
    status=modes.add_parser('google-status')
    status.add_argument('place_id')
    status.set_defaults(run=google_status)
    args=parser.parse_args()
    for candidate in args.run(args):
        print(json.dumps(candidate,ensure_ascii=False))


if __name__ == '__main__':
    main()

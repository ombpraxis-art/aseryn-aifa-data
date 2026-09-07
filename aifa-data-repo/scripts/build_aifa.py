#!/usr/bin/env python3
import csv, io, json, re, unicodedata, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

MEDS_URL = 'https://drive.aifa.gov.it/farmaci/confezioni_fornitura.csv'
ACTIVE_URL = 'https://drive.aifa.gov.it/farmaci/PA_confezioni.csv'
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'public'
SHARDS = PUBLIC / 'shards'

def download(url):
    req = urllib.request.Request(url, headers={'User-Agent':'ASERYN-AIFA-Builder/1.0'})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
    for enc in ('utf-8-sig','utf-8','latin-1'):
        try: return raw.decode(enc)
        except UnicodeDecodeError: pass
    raise RuntimeError(f'Impossibile decodificare {url}')

def norm(v):
    v = unicodedata.normalize('NFD', '' if v is None else str(v))
    v = ''.join(c for c in v if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-zA-Z0-9]+',' ',v.lower()).strip()

def clean(v):
    if v is None: return None
    v = str(v).strip().strip('"')
    return None if not v or v.upper() in {'NULL','N/A','ND'} else v

def dict_rows(text):
    try: delim = csv.Sniffer().sniff(text[:10000], delimiters=';,|\t').delimiter
    except Exception: delim = ';'
    return csv.DictReader(io.StringIO(text), delimiter=delim)

def first(row,*names):
    upper={str(k).strip().upper():v for k,v in row.items()}
    for n in names:
        if n.upper() in upper: return clean(upper[n.upper()])
    return None

def shard_key(name):
    n=norm(name)
    if not n: return 'other'
    c=n[0]
    if c.isdigit(): return '0-9'
    if 'a' <= c <= 'z': return c
    return 'other'

def main():
    PUBLIC.mkdir(exist_ok=True); SHARDS.mkdir(parents=True, exist_ok=True)
    meds=download(MEDS_URL); active=download(ACTIVE_URL)
    active_by_aic=defaultdict(list)
    for row in dict_rows(active):
        aic=first(row,'CODICE_AIC','AIC')
        if aic:
            active_by_aic[aic].append((first(row,'PRINCIPIO_ATTIVO','PA'), first(row,'QUANTITA'), first(row,'UNITA_MISURA')))

    shards=defaultdict(list); count=0; now=datetime.now(timezone.utc).isoformat()
    for row in dict_rows(meds):
        aic=first(row,'CODICE_AIC','AIC'); name=first(row,'DENOMINAZIONE','NOME')
        if not aic or not name: continue
        ingredients=[]; strengths=[]
        for ing,qty,unit in active_by_aic.get(aic,[]):
            if ing and ing not in ingredients: ingredients.append(ing)
            if qty:
                s=qty + (f' {unit}' if unit else '')
                if s not in strengths: strengths.append(s)
        item={
            'aic_code':aic,'name':name,'active_ingredient':' + '.join(ingredients) or first(row,'PA_ASSOCIATI'),
            'strength':' + '.join(strengths) or None,'pharmaceutical_form':first(row,'FORMA'),
            'package_description':first(row,'DESCRIZIONE'),'package_quantity':None,'package_unit':None,
            'company':first(row,'RAGIONE_SOCIALE'),'administrative_status':first(row,'STATO_AMMINISTRATIVO'),
            'atc_code':first(row,'CODICE_ATC'),'dosage_units':None,'supply_type':first(row,'FORNITURA'),
            'source_updated_at':None,'imported_at':now
        }
        item['search_text']=norm(' '.join(str(v) for v in [item['name'],item['active_ingredient'],item['strength'],item['package_description'],item['aic_code']] if v))
        shards[shard_key(name)].append(item); count+=1

    for old in SHARDS.glob('*.json'): old.unlink()
    for key,items in shards.items():
        items.sort(key=lambda x:(norm(x['name']),x['aic_code']))
        (SHARDS/f'{key}.json').write_text(json.dumps(items,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    index={'version':now[:10],'updated_at':now,'row_count':count,'shards':sorted(shards)}
    (PUBLIC/'index.json').write_text(json.dumps(index,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'Creati {len(shards)} shard, {count} confezioni')

if __name__ == '__main__': main()

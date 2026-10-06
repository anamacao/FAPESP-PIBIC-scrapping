"""Build one offline, updateable HTML from public exports and an optional catalog.

An optional --base-json preserves a previous private snapshot; it is never
written to GitHub by this builder. The template and color rules contain no data.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit

from plotly.offline import get_plotlyjs
from curadoria_agent import load_config, prepare, read_catalog
from source_collectors import SOURCES, canonical

ROOT=Path(__file__).resolve().parents[1]


def build(csv_path, output, diagnostics_path=None, base_json=None, catalog=None):
    config=load_config(ROOT/"config/curadoria.json")
    # The old axis meant any AI keyword, not the explicit AI/data intersection.
    config["axes"]["IA / algoritmos"]=config["axes"].pop("IA e proteção de dados", {"any_keywords":["Inteligência artificial","Algoritmos","AI Act"]})
    config["axes"]={k:v for k,v in config["axes"].items()}
    documents=[]
    previous={}
    if base_json:
        previous=json.loads(Path(base_json).read_text(encoding="utf-8"))
        documents=previous.get("documents",[])
    with Path(csv_path).open(encoding="utf-8-sig",newline="") as stream:
        incoming=list(csv.DictReader(stream))
    merged={canonical(r["url"]):dict(r) for r in documents if canonical(r.get("url"))}
    for raw in incoming:
        sid=raw.get("source_id","")
        meta=SOURCES.get(sid,(raw.get("source") or sid,"Não informada","Não informada","",""))
        config["source_names"][sid]=meta[0]
        url=canonical(raw.get("url"))
        if not url or not raw.get("title"):
            continue
        old=merged.get(url,{})
        row=dict(old,**raw)
        row.update(url=url,source=meta[0],country=raw.get("country") or meta[1],region=raw.get("region") or meta[2],
                   manually_selected=old.get("manually_selected",False),corpus="scrapers",
                   corpora=sorted(set(old.get("corpora",[]))|{"scrapers"}),
                   input_snapshots=sorted(set(old.get("input_snapshots",[]))|{"Coleta pública · "+str(raw.get("collected_at","") or datetime.now(timezone.utc).date())[:10]}))
        row["published_date"]=raw.get("published_date") or old.get("published_date","")
        row["record_type"]=raw.get("record_type") or old.get("record_type") or ("Notícia/comunicado" if row["published_date"] else "Registro sem data")
        if old.get("published_date") and not raw.get("published_date"):
            row["record_type"]=old.get("record_type",row["record_type"])
        if sid=="dataprivacy" and urlsplit(url).hostname in {"www.dataprivacybr.org","dataprivacybr.org"}:
            row["record_type"]="Publicação institucional"
        merged[url]=row
    if catalog:
        for raw in read_catalog(Path(catalog)):
            url=canonical(raw["url"])
            if url in merged:
                merged[url].update(manually_selected=True,catalog_title=raw["title"],catalog_summary=raw["summary"],
                                   catalog_source=raw["source_id"],corpora=["scrapers","catalogo"])
            else:
                merged[url]=dict(raw,url=url,record_type="Fonte curada",country="Não informada",region="Não informada",
                                 corpora=["catalogo"],input_snapshots=["Catálogo curado"])
    publisher_provenance=json.loads((ROOT/"config/publisher_provenance.json").read_text())
    for row in merged.values():
        parts=urlsplit(row["url"])
        host=(parts.hostname or "").removeprefix("www.")
        rule=next((r for r in publisher_provenance["rules"]
                   if (not r.get("catalog_only") or row.get("manually_selected"))
                   and any(host==h or host.endswith("."+h) for h in r["hosts"])
                   and (not r.get("path_prefix") or parts.path.startswith(r["path_prefix"]))),None)
        if rule:
            prior=row.get("source") or row.get("source_id","")
            row.setdefault("collector_id",row.get("source_id",""))
            if prior!=rule["source"]:
                row.setdefault("prior_source",prior)
            if row.get("manually_selected"):
                row.setdefault("catalog_credit",row.get("catalog_source") or prior)
            row.update(source_id=rule["id"],source=rule["source"],country=rule["country"],region=rule["region"],
                       source_basis="Cadastro editorial: domínio e caminho da URL",source_reference=rule["reference"])
        config["source_names"][row["source_id"]]=row.get("source") or config["source_names"].get(row["source_id"],row["source_id"])
    rows,stats=prepare(list(merged.values()),config)
    source_meta={sid:{"source":name,"country":country,"region":region,"hosts":[urlsplit(endpoint).hostname.removeprefix("www.")]} for sid,(name,country,region,endpoint,_) in SOURCES.items()}
    source_meta["dataprivacy"]["hosts"].append("dataprivacy.com.br")
    # The EU portal links to official institutions on subdomains of europa.eu.
    source_meta["ue_news"]["hosts"].append("europa.eu")
    source_meta["nic"]["hosts"].extend(["cetic.br","ix.br"])
    source_meta["google_transparency"]["hosts"].append("transparencyreport.google.com")
    for rule in publisher_provenance["rules"]:
        source_meta[rule["id"]]=dict(rule)
    for row in rows:
        sid=row["source_id"]
        if sid not in source_meta and "scrapers" in row.get("corpora",[]):
            source_meta[sid]={"source":row["source"],"country":row.get("country","Não informada"),"region":row.get("region","Não informada"),"hosts":[urlsplit(row["url"]).hostname.removeprefix("www.")]}
    diagnostics=json.loads(Path(diagnostics_path).read_text()) if diagnostics_path and Path(diagnostics_path).exists() else previous.get("diagnostics",{})
    now=datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload={"documents":rows,"config":config,"source_meta":source_meta,"publisher_provenance":publisher_provenance,"color_registry":previous.get("color_registry",{}),
             "diagnostics":diagnostics,"metadata":dict(previous.get("metadata",{}),generated_at=now,as_of=now[:10],dashboard_version="4.0",
                 analysis_text="title",counts=stats,collection_generated_at=diagnostics.get("generated_at"))}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(",",":")).replace("<",r"\u003c").replace(">",r"\u003e").replace("&",r"\u0026")
    template=(ROOT/"scripts/painel_atualizavel.html").read_text()
    page=template.replace("__CURADORIA_DATA__",encoded).replace("__SAVED_STATE__","{}").replace("__PLOTLY_JS__",get_plotlyjs()).replace("__DASHBOARD_JS__",(ROOT/"scripts/painel_atualizavel.js").read_text())
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(page,encoding="utf-8")
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv",type=Path,default=ROOT/"data/unified/public_records.csv")
    parser.add_argument("--diagnostics",type=Path,default=ROOT/"data/unified/diagnostico.json")
    parser.add_argument("--base-json",type=Path)
    parser.add_argument("--catalog",type=Path)
    parser.add_argument("--output",type=Path,default=ROOT/"reports/curadoria/latest/Painel_FAPESP_interativo.html")
    args=parser.parse_args();payload=build(args.csv,args.output,args.diagnostics,args.base_json,args.catalog)
    print(json.dumps({"html":str(args.output),"records":len(payload["documents"]),"bytes":args.output.stat().st_size},ensure_ascii=False))


if __name__=="__main__":
    main()

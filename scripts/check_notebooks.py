"""Execute the original notebooks in isolated directories and report cell failures.

This is a local validation tool. It does not assert that Google Colab itself ran.
Use --diagnostic for a one-page, install-free first pass; omit it for the
unaltered notebook and its default collection range.
"""

import argparse
import json
import contextlib
import io
import os
from pathlib import Path
import re
import signal
import sys
import tempfile
import time

import nbformat
from IPython.core.interactiveshell import InteractiveShell


DATAFRAMES = {
    "parlamento_uy": "df_db", "aaip": "df_aaip", "camaraFederal": "df_camara",
    "cgi": "df_all", "dataprivacy": "df_db", "icncongresoargentina": "df_icn",
    "internetlab": "df_internetlab", "mercociudades": "df_scraped",
    "nic_": "df_nic", "observacom": "df_observacom", "senado": "df_db",
    "senadofederal": "df_senado_filtered", "urcdp": "df_urcdp",
    "charts": "df_all", "comissaoEuropeia": "df_scraped",
    "database_analysis": "df", "edpb": "df_edpb", "google_transparency": "df_final",
    "icann": "df", "uniaoEuropeia": "df_ue", "uniaoEuropeia_news (EUR-Lex)": "df_eu",
}


def timeout_handler(signum, frame):
    raise TimeoutError("Célula excedeu o limite de tempo")


def prepare(nb, diagnostic):
    if not diagnostic:
        return nb
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        code = cell.source
        code = re.sub(r"(?m)^\s*(?:%pip|!pip|!apt-get|!\{sys\.executable\} -m pip).*?$", "# dependency already provisioned for diagnostic", code)
        code = re.sub(r"(?m)^(TOTAL_PAGES|MAX_PAGES)\s*=\s*\d+", r"\1 = 1", code)
        code = re.sub(r"(scrape_cgi_noticias\(max_pages=)\d+", r"\g<1>1", code)
        code = re.sub(r"(scrape_european_commission_debug\(max_pages=)\d+", r"\g<1>1", code)
        code = re.sub(r"(scrape_ue\(max_page=)\d+", r"\g<1>1", code)
        code = re.sub(r"(scrape_mercociudades\(page_final=)\d+", r"\g<1>1", code)
        cell.source = code
    return nb


def execute(path, diagnostic, cell_timeout):
    nb = prepare(nbformat.read(path, as_version=4), diagnostic)
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="fapesp-notebook-") as tmp:
        previous = os.getcwd()
        os.chdir(tmp)
        shell = InteractiveShell.instance()
        shell.reset(new_session=True)
        shell.user_ns["__name__"] = "__main__"
        cells = []
        error = None
        try:
            for index, cell in enumerate(c for c in nb.cells if c.cell_type == "code"):
                stream = io.StringIO()
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(cell_timeout)
                try:
                    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                        result = shell.run_cell(cell.source, store_history=False)
                finally:
                    signal.alarm(0)
                failure = result.error_before_exec or result.error_in_exec
                log = stream.getvalue()
                cells.append({"index": index, "ran": True, "log": log[-600:]})
                if failure:
                    error = f"cell {index}: {type(failure).__name__}: {failure}\n{log[-800:]}"
                    break
        finally:
            os.chdir(previous)
        variable = DATAFRAMES[path.stem]
        dataset = shell.user_ns.get(variable)
        rows = len(dataset) if dataset is not None else None
        if error is None and not rows:
            error = f"{variable} está vazio ou ausente: nenhuma coleta validada"
        return {"notebook": str(path), "diagnostic": diagnostic, "seconds": round(time.monotonic() - start, 1), "rows": rows, "status": "pass" if error is None else "fail", "error": error, "cells": cells}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("notebooks", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="Executar os 21 notebooks originais")
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--cell-timeout", type=int, default=300)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.all:
        args.notebooks = sorted(Path("Mercosul").rglob("*.ipynb")) + sorted(Path("UE").rglob("*.ipynb"))
    if not args.notebooks:
        parser.error("Informe notebooks ou use --all")
    results = []
    for path in args.notebooks:
        result = execute(path, args.diagnostic, args.cell_timeout)
        results.append(result)
        ran = sum(c["ran"] for c in result["cells"])
        print(f"{result['status'].upper()} {path} {ran}/{len(result['cells'])} cells {result['rows']} rows {result['seconds']}s", flush=True)
        if result["error"]:
            print(result["error"][-700:], flush=True)
    if args.output:
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    if any(result["status"] != "pass" for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()

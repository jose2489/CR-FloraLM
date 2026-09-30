"""Freeze the GBIF occurrence snapshot as a citable download DOI (for the paper).

The analysis uses the live GBIF search API (no DOI). For the final paper, GBIF
recommends issuing a *download* — a citable, versioned snapshot with a DOI. This
helper submits the download matching our methodology (Costa Rica vascular plants,
georeferenced, no geospatial issue) and returns the DOI once ready.

Needs a free GBIF account. Add to .env:  GBIF_USER, GBIF_PWD, GBIF_EMAIL
Then:  python -m mpcr_rag.eval.gbif_download submit          → prints a download key
       python -m mpcr_rag.eval.gbif_download status <key>    → prints DOI when ready
"""
from __future__ import annotations

import os

from pygbif import occurrences

from .. import config  # noqa: F401  (imported for its side effect: loads .env)

# Predicate matching the analysis: CR vascular plants, georeferenced, clean flags.
# taxonKey 7707728 = Tracheophyta. Our extra coordinate cleaning is applied locally.
_QUERY = [
    "country = CR",
    "taxonKey = 7707728",
    "hasCoordinate = true",
    "hasGeospatialIssue = false",
]

# Equivalent GBIF web filter (Occurrences search), for the manual route:
_WEB = ("https://www.gbif.org/occurrence/search?"
        "country=CR&taxon_key=7707728&has_coordinate=true&has_geospatial_issue=false")


def _creds():
    return (os.environ.get("GBIF_USER"), os.environ.get("GBIF_PWD"),
            os.environ.get("GBIF_EMAIL"))


def submit() -> None:
    user, pwd, email = _creds()
    if not all((user, pwd, email)):
        print("Sin credenciales GBIF. Dos rutas para obtener el DOI:\n")
        print("A) WEB (inmediata): inicia sesión en gbif.org, abre este filtro y")
        print(f"   pulsa 'Download' (Darwin Core / Simple):\n   {_WEB}\n")
        print("B) API: crea una cuenta gratis en gbif.org, agrega a .env:")
        print("   GBIF_USER=...   GBIF_PWD=...   GBIF_EMAIL=...")
        print("   y vuelve a correr `submit`.\n")
        print("Predicado del dataset (la consulta exacta):")
        for q in _QUERY:
            print(f"   {q}")
        return
    key = occurrences.download(_QUERY, user=user, pwd=pwd, email=email, pred_type="and")
    key = key[0] if isinstance(key, (list, tuple)) else key
    print(f"Descarga enviada. KEY = {key}")
    print(f"Revisa estado/DOI:  python -m mpcr_rag.eval.gbif_download status {key}")


def status(key: str) -> None:
    meta = occurrences.download_meta(key)
    st = meta.get("status")
    print(f"status: {st}   records: {meta.get('totalRecords')}")
    if meta.get("doi"):
        doi = meta["doi"]
        print(f"DOI: https://doi.org/{doi}")
        print(f"cita: GBIF.org ({(meta.get('created') or '')[:10]}) "
              f"GBIF Occurrence Download https://doi.org/{doi}")
    elif st == "SUCCEEDED":
        print("Lista, pero sin DOI en meta — revisa el portal de descargas en gbif.org.")
    else:
        print("Aún procesando; reintenta en unos minutos.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2 and sys.argv[1] == "status":
        status(sys.argv[2])
    else:
        submit()

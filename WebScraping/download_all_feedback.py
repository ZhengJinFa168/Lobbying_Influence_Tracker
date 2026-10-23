#!/usr/bin/env python3
"""
download_all_feedback.py
========================
Script parametrico per lo scraping dei feedback pubblici della Commissione Europea
(Have Your Say) per entrambe le fasi:
  - Stage 1: Inception Impact Assessment
  - Stage 2: Proposal for a Regulation

Supporta qualsiasi procedura legislativa definita in data_sources/procedures/<id>.yaml (default: ai_act).

Filtra sia l'industria che la società civile:
  - COMPANY
  - BUSINESS_ASSOCIATION
  - NGO
  - CONSUMER_ORGANISATION
  - TRADE_UNION

Autore: Antigravity AI (Senior Data Engineer)
"""

import urllib.request
import urllib.parse
import json
import time
import os
import sys
import re
import argparse
from typing import Dict, Any, List, Optional
import yaml

# =====================================================================
# CONFIGURAZIONE GENERALE E COSTANTI
# =====================================================================

BASE_URL = "https://ec.europa.eu/info/law/better-regulation/api/allFeedback"
DOWNLOAD_URL_TEMPLATE = "https://ec.europa.eu/info/law/better-regulation/api/download/{document_id}"

# Filtro Lobbisti e Società Civile
TARGET_USER_TYPES = {
    "COMPANY",                  # Grandi aziende tecnologiche e fornitori
    "BUSINESS_ASSOCIATION",     # Federazioni industriali (DIGITALEUROPE, CCIA, ecc.)
    "NGO",                      # ONG e diritti digitali (EDRi, Access Now, AlgorithmWatch)
    "CONSUMER_ORGANISATION",    # Associazioni dei consumatori (BEUC, ecc.)
    "TRADE_UNION"               # Sindacati dei lavoratori
}

def load_stages_config(procedure_id: str = "ai_act", base_dir: Optional[str] = None) -> Dict[int, Dict[str, Any]]:
    """
    Carica la configurazione degli stage da data_sources/procedures/<procedure_id>.yaml.
    Mappa:
      - consultation.A.publication -> Stage 1 ("inception", cartella feedback/stage1_inception_<pub>/)
      - consultation.B.publication -> Stage 2 ("proposal", cartella feedback/stage2_proposal_<pub>/)
    I track la cui pubblicazione è null vengono ignorati.
    """
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(base_dir, ".."))
    proc_id = procedure_id.strip().removesuffix(".yaml")
    procedures_dir = os.path.join(repo_root, "data_sources", "procedures")
    yaml_path = os.path.join(procedures_dir, f"{proc_id}.yaml")

    if not os.path.isfile(yaml_path):
        known = ", ".join(sorted(f.removesuffix(".yaml") for f in os.listdir(procedures_dir) if f.endswith(".yaml")))
        raise SystemExit(f"unknown procedure {proc_id!r}: expected data_sources/procedures/<id>.yaml, one of: {known}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    consultation = data.get("consultation", {})
    configs: Dict[int, Dict[str, Any]] = {}

    # Stage 1: Track A (inception)
    cA = consultation.get("A")
    if isinstance(cA, dict) and cA.get("publication") is not None:
        pub_a = int(cA["publication"])
        folder_a = f"feedback/stage1_inception_{pub_a}"
        if proc_id == "ai_act":
            title_a = "Stage 1 (Inception Impact Assessment 2020 - PubID 13340)"
        else:
            label_a = (cA.get("label") or "Inception Impact Assessment").strip()
            title_a = f"Stage 1 ({label_a} - PubID {pub_a})"

        configs[1] = {
            "publication_id": pub_a,
            "stage_name": "STAGE_1_INCEPTION_FEEDBACK",
            "title": title_a,
            "folder": folder_a,
            "output_file": f"{folder_a}/raw_feedback_stage1_{pub_a}.json",
            "raw_json": f"{folder_a}/raw_feedback_stage1_{pub_a}.json",
            "parsed_json": f"{folder_a}/parsed_feedback_stage1_{pub_a}.json",
            "attachments_dir": f"{folder_a}/attachments",
        }

    # Stage 2: Track B (proposal)
    cB = consultation.get("B")
    if isinstance(cB, dict) and cB.get("publication") is not None:
        pub_b = int(cB["publication"])
        folder_b = f"feedback/stage2_proposal_{pub_b}"
        if proc_id == "ai_act":
            title_b = "Stage 2 (Proposal for a Regulation 2021 - PubID 14488)"
        else:
            label_b = (cB.get("label") or "Proposal for a Regulation").strip()
            title_b = f"Stage 2 ({label_b} - PubID {pub_b})"

        configs[2] = {
            "publication_id": pub_b,
            "stage_name": "STAGE_2_PROPOSAL_FEEDBACK",
            "title": title_b,
            "folder": folder_b,
            "output_file": f"{folder_b}/raw_feedback_stage2_{pub_b}.json",
            "raw_json": f"{folder_b}/raw_feedback_stage2_{pub_b}.json",
            "parsed_json": f"{folder_b}/parsed_feedback_stage2_{pub_b}.json",
            "attachments_dir": f"{folder_b}/attachments",
        }

    return configs


# Configurazione di default per retrocompatibilità (ai_act)
STAGES_CONFIG = load_stages_config("ai_act")

SHORT_COMMENT_THRESHOLD = 200

HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7',
    'Cache-Control': 'No-Cache',
    'Connection': 'keep-alive',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36',
    'X-Requested-With': 'XMLHttpRequest',
    'sec-ch-ua': '"Chromium";v="152", "Not?A_Brand";v="24", "Google Chrome";v="152"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'Cookie': 'cck1=%7B%22cm%22%3Atrue%2C%22all1st%22%3Atrue%7D; _pcid=%7B%22browserId%22%3A%22muri8ry0l9ke34hg%22%2C%22_t%22%3A%22nafzbf26%7Cmuri8ry6%22%7D; _pctx=%7Bu%7DN4IgrgzgpgThIC4B2YA2qA05owMoBcBDfSREQpAeyRCwgEt8oBJAE0RXSwH18ylCAMwBeAI0EAmAOwAfALZgY9ABwwAnlJABfIA; _pprv=eyJjb25zZW50Ijp7IjAiOnsibW9kZSI6Im9wdC1pbiJ9LCI3Ijp7Im1vZGUiOiJvcHQtaW4ifX0sInB1cnBvc2VzIjp7IjAiOiJBTSIsIjciOiJETCJ9LCJfdCI6Im5hZnpiZjIyfG11cmk4cnkyIn0%3D; dtCookie=v_4_srv_56_sn_30E33035B60ABF6B78ABD5A2A000EE02_perc_100000_ol_0_mul_1_app-3A47d4c64c3b67ec69_0_app-3A9daca62c888adcd6_1_rcs-3Acss_0'
}


# =====================================================================
# FUNZIONI DI UTILITÀ
# =====================================================================

def sanitize_filename(filename: str) -> str:
    """Rimuove caratteri vietati nei filesystem preservando la leggibilità."""
    cleaned = re.sub(r'[\\/*?:"<>|]', '_', filename)
    return re.sub(r'\s+', ' ', cleaned).strip()


def is_comment_too_short(text: str) -> bool:
    """True se il commento è breve o rimanda esplicitamente all'allegato."""
    if not text or len(text.strip()) < SHORT_COMMENT_THRESHOLD:
        return True
    triggers = [
        "attached", "attachment", "allegat", "see file", "in the file",
        "position paper", "submission", "find enclosed", "please find",
        "detailed comments", "enclosed document", "contribution is attached",
        "recomemndations", "recommendations in the attached"
    ]
    text_lower = text.lower()
    return any(t in text_lower for t in triggers)


def download_attachment_file(url: str, output_path: str, max_retries: int = 3) -> bool:
    """Scarica il file allegato gestendo connessione e retry."""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        return True

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    req = urllib.request.Request(url, headers=HEADERS)

    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()
                if len(content) > 100:
                    with open(output_path, "wb") as f:
                        f.write(content)
                    return True
        except Exception as e:
            if attempt < max_retries:
                time.sleep(1.0 * attempt)
            else:
                print(f"      ⚠️ Errore download ({url}): {e}")
                return False
    return False


def extract_text_from_file(file_path: str) -> str:
    """
    Estrae testo da PDF o DOCX rilevando il formato reale
    tramite 'magic bytes' anziché affidarsi solo all'estensione del nome.
    """
    if not os.path.exists(file_path):
        return ""

    # Lettura dei magic bytes
    try:
        with open(file_path, "rb") as f:
            magic = f.read(5)
    except Exception:
        magic = b""

    # Riconoscimento PDF (standard o convertito dall'API della Commissione)
    if magic.startswith(b"%PDF"):
        try:
            import pypdf
            reader = pypdf.PdfReader(file_path)
            pages = [page.extract_text() or "" for page in reader.pages]
            txt = "\n".join(pages).strip()
            if len(txt) > 50:
                return txt
        except Exception:
            pass

        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
                return "\n".join(pages).strip()
        except Exception:
            pass

    # Riconoscimento DOCX (formato zip PK\x03\x04)
    elif magic.startswith(b"PK"):
        try:
            import docx
            doc = docx.Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except Exception:
            pass

    return ""


# =====================================================================
# MOTORE DI DOWNLOAD PER SINGOLO STAGE
# =====================================================================

def download_stage(stage_num: int, base_dir: str, stages_config: Optional[Dict[int, Dict[str, Any]]] = None):
    if stages_config is None:
        stages_config = STAGES_CONFIG
    conf = stages_config[stage_num]
    pub_id = conf["publication_id"]
    stage_name = conf["stage_name"]
    output_file = os.path.join(base_dir, conf["output_file"])
    attachments_dir = os.path.join(base_dir, conf["attachments_dir"])
    rel_attachments_dir = conf["attachments_dir"]

    os.makedirs(attachments_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    print("\n" + "=" * 70)
    print(f"🚀 AVVIO DOWNLOAD: {conf['title']}")
    print(f"🎯 Filtro UserTypes attivi: {TARGET_USER_TYPES}")
    print(f"📁 Cartella allegati: '{rel_attachments_dir}/'")
    print(f"💾 File JSON grezzo: '{conf['output_file']}'")
    print("=" * 70)

    all_filtered = []
    user_type_counts: Dict[str, int] = {}
    page = 0
    page_size = 25
    total_processed = 0

    while True:
        url = (
            f"{BASE_URL}?publicationId={pub_id}&language=EN"
            f"&page={page}&size={page_size}&sort=dateFeedback,DESC"
        )
        req = urllib.request.Request(url, headers=HEADERS)

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status != 200:
                    print(f"⚠️ Errore HTTP {resp.status} a pagina {page}")
                    break

                data = json.loads(resp.read().decode('utf-8'))
                items = data.get("content", [])
                total = data.get("totalElements", 0)
                is_last = data.get("last", False)

                if not items:
                    print(f"✅ Nessun elemento a pagina {page}.")
                    break

                total_processed += len(items)

                for item in items:
                    user_type = item.get("userType", "")

                    if user_type not in TARGET_USER_TYPES:
                        continue

                    user_type_counts[user_type] = user_type_counts.get(user_type, 0) + 1
                    raw_feedback_text = item.get("feedback", "") or ""
                    attachments = item.get("attachments", []) or []
                    attached_texts = []

                    needs_attachment = is_comment_too_short(raw_feedback_text) and len(attachments) > 0

                    for att in attachments:
                        orig_fn = (
                            att.get("fileName")
                            or att.get("ersFileName")
                            or f"attachment_{att.get('id')}.pdf"
                        )
                        safe_fn = sanitize_filename(orig_fn)

                        local_path = os.path.join(attachments_dir, safe_fn)
                        rel_path = os.path.join(rel_attachments_dir, safe_fn)
                        doc_id = att.get("documentId")

                        att["localFilePath"] = rel_path
                        att["downloadUrl"] = DOWNLOAD_URL_TEMPLATE.format(document_id=doc_id) if doc_id else None

                        if needs_attachment and doc_id:
                            org_name = item.get("organization") or "N/A"
                            print(f"   📥 [{user_type}] Allegato per '{org_name}': {safe_fn}")
                            ok = download_attachment_file(att["downloadUrl"], local_path)
                            if ok:
                                extracted = extract_text_from_file(local_path)
                                if extracted:
                                    att["extractedTextLength"] = len(extracted)
                                    attached_texts.append(extracted)

                    # Tracciamento e testo integrato
                    full_comment_parts = []
                    if raw_feedback_text.strip():
                        full_comment_parts.append(raw_feedback_text.strip())
                    if attached_texts:
                        full_comment_parts.append("\n\n--- [TESTO ALLEGATO] ---\n\n" + "\n\n".join(attached_texts))

                    item["stage_name"] = stage_name
                    item["publication_id"] = pub_id
                    item["full_comment"] = "\n\n".join(full_comment_parts)
                    item["has_attachment_downloaded"] = len(attached_texts) > 0

                    all_filtered.append(item)

                print(f"📦 Pagina {page}: letti {total_processed}/{total} | Target salvati: {len(all_filtered)}")

                if is_last or total_processed >= total:
                    print("🎉 Raggiunto l'ultimo elemento della consultazione!")
                    break

                page += 1
                time.sleep(0.35)

        except urllib.error.URLError as e:
            print(f"⚠️ Errore di rete a pagina {page}: {e}. Riprovo tra 3 secondi...")
            time.sleep(3.0)
            continue
        except Exception as e:
            print(f"❌ Errore imprevisto a pagina {page}: {e}")
            break

    # Scrittura JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_filtered, f, indent=2, ensure_ascii=False)

    print("\n" + "-" * 50)
    print(f"✨ Completato {conf['title']}!")
    print(f"💾 Record salvati: {len(all_filtered)} in '{output_file}'")
    print(f"📊 Distribuzione per UserType:")
    for ut, cnt in sorted(user_type_counts.items(), key=lambda x: -x[1]):
        print(f"    • {ut:25}: {cnt}")
    print("-" * 50 + "\n")


# =====================================================================
# CLI
# =====================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Scarica i feedback e gli allegati per le consultazioni della Commissione Europea (Have Your Say)."
    )
    parser.add_argument(
        "--procedure", "-p",
        default="ai_act",
        help="ID procedura in data_sources/procedures/<id>.yaml (default: ai_act)"
    )
    parser.add_argument(
        "--stage", "-s",
        choices=["1", "2", "all"],
        default="all",
        help="Quale stage scaricare: '1', '2' oppure 'all' (default: all)"
    )

    args = parser.parse_args()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    stages_config = load_stages_config(args.procedure, script_dir)

    if args.stage in ["1", "all"]:
        if 1 in stages_config:
            download_stage(1, script_dir, stages_config)
        elif args.stage == "1":
            print(f"⚠️ Stage 1 non configurato per la procedura '{args.procedure}' (publication è null).")

    if args.stage in ["2", "all"]:
        if 2 in stages_config:
            download_stage(2, script_dir, stages_config)
        elif args.stage == "2":
            print(f"⚠️ Stage 2 non configurato per la procedura '{args.procedure}' (publication è null).")


if __name__ == "__main__":
    main()

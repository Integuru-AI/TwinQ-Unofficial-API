import re
import json as json_mod
import html as html_module
import urllib.parse
import base64 as _b64
from curl_cffi import requests


def run(headers, user_input):
    """Create a new melding (notification/report) via Technisch > Meldingen & Opdrachten."""
    base_url = BASE_URL.rstrip("/")

    # Validate required inputs
    vve = user_input.get("vve")
    melder = user_input.get("melder")
    datum = user_input.get("datum")
    tijd = user_input.get("tijd")
    meldingskanaal = user_input.get("meldingskanaal")
    onderwerp = user_input.get("onderwerp")
    toelichting = user_input.get("toelichting", "") or onderwerp or ""

    if not vve:
        return {"status_code": 400, "body": {"error": "vve is required"}}
    if not melder:
        return {"status_code": 400, "body": {"error": "melder is required"}}
    if not datum:
        return {"status_code": 400, "body": {"error": "datum is required"}}
    if not tijd:
        return {"status_code": 400, "body": {"error": "tijd is required"}}
    if not meldingskanaal:
        return {"status_code": 400, "body": {"error": "meldingskanaal is required"}}
    if not onderwerp:
        return {"status_code": 400, "body": {"error": "onderwerp is required"}}

    # Convert date from YYYY-MM-DD to DD-MM-YYYY
    try:
        parts = datum.split("-")
        datum_formatted = f"{parts[2]}-{parts[1]}-{parts[0]}"
    except (IndexError, AttributeError):
        return {"status_code": 400, "body": {"error": "datum must be in YYYY-MM-DD format"}}

    # Combine date and time in DD-MM-YYYY HH:MM format
    datum_tijd = f"{datum_formatted} {tijd}"

    # Step 1: Load the meldingen list page (411000) to get navigation checksum
    resp = requests.get(
        f"{base_url}/apex/f?p=170:411000::::::",
        headers=headers,
        impersonate="chrome131",
        timeout=30,
        allow_redirects=False,
    )

    # Check for login redirect (302 to LOGIN_DESKTOP)
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        if "LOGIN" in location.upper():
            return {"status_code": 401, "body": {"error": "Session expired"}}
        # Follow redirect to the actual page
        if not location.startswith("http"):
            location = f"{base_url}{location}"
        resp = requests.get(
            location,
            headers=headers,
            impersonate="chrome131",
            timeout=30,
            allow_redirects=False,
        )

    if resp.status_code != 200:
        return {"status_code": resp.status_code, "body": {"error": "Failed to load meldingen page"}}

    page_411000 = resp.text

    # Check for login page content
    if "P101_USERNAME" in page_411000 or "LOGIN_DESKTOP" in page_411000:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    # Extract instance from pContext
    ctx_match = re.search(r'value="([^"]*)"[^>]*id="pContext"', page_411000)
    if not ctx_match:
        ctx_match = re.search(r'id="pContext"[^>]*value="([^"]*)"', page_411000)
    if ctx_match:
        ctx_val = html_module.unescape(ctx_match.group(1))
        ctx_parts = ctx_val.split(":")
        if len(ctx_parts) >= 3:
            p_instance = ctx_parts[2]
        else:
            return {"status_code": 500, "body": {"error": "Could not extract instance"}}
    else:
        return {"status_code": 500, "body": {"error": "Could not extract instance from page"}}

    # Extract the navigation URL with cs to get to 411050
    # The & before cs= may appear as literal &, as &#x26;, as &, or as &amp;
    cs_match = re.search(
        r"f\?p=170:411050[^'\"]*?cs=([A-Za-z0-9_\-]+)",
        page_411000,
    )
    if not cs_match:
        return {"status_code": 500, "body": {"error": "Could not find navigation checksum for create page"}}

    cs_value = cs_match.group(1)

    # Step 2: Load the create form page (411050)
    form_url = f"{base_url}/apex/f?p=170:411050::::RP,411050::&cs={cs_value}"
    resp = requests.get(
        form_url,
        headers=headers,
        impersonate="chrome131",
        timeout=30,
        allow_redirects=False,
    )

    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        if "LOGIN" in location.upper():
            return {"status_code": 401, "body": {"error": "Session expired"}}
        if not location.startswith("http"):
            location = f"{base_url}{location}"
        resp = requests.get(
            location,
            headers=headers,
            impersonate="chrome131",
            timeout=30,
            allow_redirects=False,
        )

    if resp.status_code != 200:
        return {"status_code": resp.status_code, "body": {"error": "Failed to load create form"}}

    page_411050 = resp.text

    if "Session state protection violation" in page_411050:
        return {"status_code": 500, "body": {"error": "Session state protection violation"}}
    if "P101_USERNAME" in page_411050 or "LOGIN_DESKTOP" in page_411050:
        return {"status_code": 401, "body": {"error": "Session expired"}}

    # Extract session values from the form page
    salt_match = re.search(r'value="([^"]*)"[^>]*id="pSalt"', page_411050)
    if not salt_match:
        return {"status_code": 500, "body": {"error": "Could not extract salt"}}
    salt = html_module.unescape(salt_match.group(1))

    psid_match = re.search(r'name="p_page_submission_id"\s+value="([^"]*)"', page_411050)
    if not psid_match:
        return {"status_code": 500, "body": {"error": "Could not extract page submission ID"}}
    p_page_submission_id = html_module.unescape(psid_match.group(1))

    protected_match = re.search(r'id="pPageItemsProtected"\s+value="([^"]*)"', page_411050)
    if not protected_match:
        return {"status_code": 500, "body": {"error": "Could not extract protected items"}}
    protected_value = html_module.unescape(protected_match.group(1))

    # Update p_instance from form page context
    ctx_match = re.search(r'value="([^"]*)"[^>]*id="pContext"', page_411050)
    if ctx_match:
        ctx_val = html_module.unescape(ctx_match.group(1))
        ctx_parts = ctx_val.split(":")
        if len(ctx_parts) >= 3:
            p_instance = ctx_parts[2]

    # Extract checksums for protected items
    ck_items = re.findall(
        r'<input\s+type="hidden"\s+data-for="([^"]+)"\s+value="([^"]*)"',
        page_411050,
    )
    checksums = {}
    for name, ck in ck_items:
        checksums[name] = html_module.unescape(ck)

    # Extract default hidden values
    def get_hidden_value(item_name):
        match = re.search(
            rf'name="{item_name}"\s+id="{item_name}"\s+value="([^"]*)"',
            page_411050,
        )
        if match:
            return html_module.unescape(match.group(1))
        match2 = re.search(rf'id="{item_name}"[^>]*value="([^"]*)"', page_411050)
        if match2:
            return html_module.unescape(match2.group(1))
        return ""

    twkl_nr = get_hidden_value("P411050_TWKL_NR")

    # Extract ajaxIdentifiers for VVES_NR and MELDER lookups
    vves_ajax_match = re.search(
        r'ajaxIdentifier:\s*"([^"]+)"[^}]*pageItemId:\s*"P411050_VVES_NR"',
        page_411050,
    )
    if not vves_ajax_match:
        return {"status_code": 500, "body": {"error": "Could not find VVES_NR ajax identifier"}}
    vves_ajax_id = vves_ajax_match.group(1)

    melder_ajax_match = re.search(
        r'ajaxIdentifier:\s*"([^"]+)"[^}]*pageItemId:\s*"P411050_MELDER"',
        page_411050,
    )
    if not melder_ajax_match:
        return {"status_code": 500, "body": {"error": "Could not find MELDER ajax identifier"}}
    melder_ajax_id = melder_ajax_match.group(1)

    # Extract defaults for VERZ_TYPE, BMDW_NR, URGENTIE
    verz_type_default = "ONDH"
    vt_section = re.search(r'pageItemId:\s*"P411050_VERZ_TYPE",\s*selectedItems:\s*\[([^\]]*)\]', page_411050)
    if vt_section:
        vt_r = re.search(r'"r":"([^"]+)"', vt_section.group(1))
        if vt_r:
            verz_type_default = vt_r.group(1)

    bmdw_default = ""
    bmdw_section = re.search(r'pageItemId:\s*"P411050_BMDW_NR",\s*selectedItems:\s*\[([^\]]*)\]', page_411050)
    if bmdw_section:
        bmdw_r = re.search(r'"r":"([^"]+)"', bmdw_section.group(1))
        if bmdw_r:
            bmdw_default = bmdw_r.group(1)

    urgentie_default = "ADRG"
    urg_section = re.search(r'pageItemId:\s*"P411050_URGENTIE",\s*selectedItems:\s*\[([^\]]*)\]', page_411050)
    if urg_section:
        urg_r = re.search(r'"r":"([^"]+)"', urg_section.group(1))
        if urg_r:
            urgentie_default = urg_r.group(1)

    # Step 3: Look up VVES_NR from display name
    ajax_url = f"{base_url}/apex/wwv_flow.ajax?p_context=170:411050:{p_instance}"
    ajax_headers = {
        **headers,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": form_url,
        "Origin": base_url,
    }

    vves_payload = urllib.parse.urlencode({
        "p_flow_id": "170",
        "p_flow_step_id": "411050",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": f"PLUGIN={vves_ajax_id}",
        "x01": "GET_ITEMS",
        "x02": "0",
        "p_json": json_mod.dumps({"salt": salt}),
    })

    resp = requests.post(
        ajax_url,
        headers=ajax_headers,
        data=vves_payload.encode("utf-8"),
        impersonate="chrome131",
        timeout=30,
    )
    if resp.status_code != 200:
        return {"status_code": 500, "body": {"error": "Failed to fetch VvE list"}}

    vves_data = resp.json()
    vves_nr = None
    for item in vves_data.get("items", []):
        if item.get("d", "").lower() == vve.lower():
            vves_nr = item["r"]
            break
    if not vves_nr:
        for item in vves_data.get("items", []):
            if vve.lower() in item.get("d", "").lower():
                vves_nr = item["r"]
                break
    if not vves_nr:
        return {"status_code": 400, "body": {"error": f"VvE '{vve}' not found"}}

    # Step 4: Look up MELDER from display name (cascading from VVES_NR)
    melder_json = {
        "salt": salt,
        "pageItems": {
            "itemsToSubmit": [
                {"n": "P411050_IND_MELDER_BINNEN_VVE", "v": "1"},
                {"n": "P411050_RELA_NR", "v": ""},
                {"n": "P411050_CTPS_NR", "v": ""},
                {"n": "P411050_VVES_NR", "v": vves_nr},
            ],
            "protected": protected_value,
            "rowVersion": "",
            "formRegionChecksums": [],
        },
    }

    melder_payload = urllib.parse.urlencode({
        "p_flow_id": "170",
        "p_flow_step_id": "411050",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": f"PLUGIN={melder_ajax_id}",
        "x01": "GET_ITEMS",
        "x02": "0",
        "p_json": json_mod.dumps(melder_json),
    })

    resp = requests.post(
        ajax_url,
        headers=ajax_headers,
        data=melder_payload.encode("utf-8"),
        impersonate="chrome131",
        timeout=30,
    )
    if resp.status_code != 200:
        return {"status_code": 500, "body": {"error": "Failed to fetch melder list"}}

    melder_data = resp.json()
    melder_value = None
    for item in melder_data.get("items", []):
        if item.get("d", "").lower() == melder.lower():
            melder_value = item["r"]
            break
    if not melder_value:
        for item in melder_data.get("items", []):
            if melder.lower() in item.get("d", "").lower():
                melder_value = item["r"]
                break
    if not melder_value:
        return {"status_code": 400, "body": {"error": f"Melder '{melder}' not found in VvE"}}

    # melder_value can be "RELA_NR" or "RELA_NR:CTPS_NR" format
    if ":" in str(melder_value):
        rela_nr = melder_value.split(":")[0]
        ctps_nr = melder_value.split(":")[1]
    else:
        rela_nr = melder_value
        ctps_nr = ""

    # Step 5: Submit the form
    items_to_submit = [
        {"n": "P0_VVE_FILTER", "v": ""},
        {"n": "P411050_BREADCRUMB_SHORT", "v": "Nieuwe melding", "ck": checksums.get("P411050_BREADCRUMB_SHORT", "")},
        {"n": "P411050_BREADCRUMB_LONG", "v": "", "ck": checksums.get("P411050_BREADCRUMB_LONG", "")},
        {"n": "P0_BEHA_NR", "v": ""},
        {"n": "P0_BEHA_LABEL", "v": ""},
        {"n": "P411050_NR", "v": "", "ck": checksums.get("P411050_NR", "")},
        {"n": "P411050_IND_MELDER_BINNEN_VVE", "v": "1"},
        {"n": "P411050_RELA_NR", "v": rela_nr},
        {"n": "P411050_CTPS_NR", "v": ctps_nr},
        {"n": "P411050_TWKL_NR", "v": twkl_nr, "ck": checksums.get("P411050_TWKL_NR", "")},
        {"n": "P411050_IND_MLDR_ALLE_APPR_TOEGEVOEGD", "v": "0"},
        {"n": "P411050_IND_BRON_GEREGISTREERD_BHDR", "v": "", "ck": checksums.get("P411050_IND_BRON_GEREGISTREERD_BHDR", "")},
        {"n": "P411050_MELDING_STATUS", "v": "", "ck": checksums.get("P411050_MELDING_STATUS", "")},
        {"n": "P411050_IND_S1_CHAT_BESCHIKBAAR", "v": "", "ck": checksums.get("P411050_IND_S1_CHAT_BESCHIKBAAR", "")},
        {"n": "P411050_IND_S1_IS_BRON", "v": "", "ck": checksums.get("P411050_IND_S1_IS_BRON", "")},
        {"n": "P411050_IND_OPDR_AANWEZIG", "v": "", "ck": checksums.get("P411050_IND_OPDR_AANWEZIG", "")},
        {"n": "P411050_IND_CORRESPONDENTIE_AANWEZIG", "v": ""},
        {"n": "P411050_OPDR_NR", "v": ""},
        {"n": "P411050_VVES_NR", "v": vves_nr},
        {"n": "P411050_MELDER", "v": melder_value},
        {"n": "P411050_RELA_ALLE_TEKST", "v": "i.p.v. relaties binnen de VvE", "ck": checksums.get("P411050_RELA_ALLE_TEKST", "")},
        {"n": "P411050_RELA_BINNEN_TEKST", "v": "i.p.v. over alle relaties", "ck": checksums.get("P411050_RELA_BINNEN_TEKST", "")},
        {"n": "P411050_DATUM", "v": datum_tijd},
        {"n": "P411050_BRON", "v": meldingskanaal},
        {"n": "P411050_OMSCHRIJVING_KORT", "v": onderwerp},
        {"n": "P411050_OMSCHRIJVING", "v": toelichting},
        {"n": "P411050_APPARTEMENTSRECHTEN", "v": ""},
        {"n": "P411050_BOUWDELEN", "v": ""},
        {"n": "P411050_VERZ_TYPE", "v": verz_type_default},
        {"n": "P411050_BMDW_NR", "v": bmdw_default},
        {"n": "P411050_URGENTIE", "v": urgentie_default},
        {"n": "P411050_IND_PUBL_WEB", "v": "1"},
        {"n": "P0_IND_READONLY", "v": "", "ck": checksums.get("P0_IND_READONLY", "")},
        {"n": "P411050_AANTAL_BKMK", "v": "0"},
        {"n": "P411050_AANTAL_SPRG", "v": "0"},
        {"n": "P411050_IND_KENMERKEN", "v": "0"},
        {"n": "P411050_BEHEERKENMERKEN_ZOEK", "v": ""},
        {"n": "P411050_SPLITSINGSREGLEMENT_ZOEK", "v": ""},
    ]

    p_json_data = {
        "pageItems": {
            "itemsToSubmit": items_to_submit,
            "protected": protected_value,
            "rowVersion": "",
            "formRegionChecksums": [],
        },
        "salt": salt,
    }

    submit_payload = urllib.parse.urlencode({
        "p_flow_id": "170",
        "p_flow_step_id": "411050",
        "p_instance": p_instance,
        "p_debug": "",
        "p_request": "CREATE",
        "p_reload_on_submit": "S",
        "p_page_submission_id": p_page_submission_id,
        "p_json": json_mod.dumps(p_json_data),
    })

    submit_headers = {
        **headers,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": form_url,
        "Origin": base_url,
    }

    submit_url = f"{base_url}/apex/wwv_flow.accept?p_context=170:411050:{p_instance}"
    resp = requests.post(
        submit_url,
        headers=submit_headers,
        data=submit_payload.encode("utf-8"),
        impersonate="chrome131",
        timeout=30,
        allow_redirects=False,
    )

    # Handle submit response - strict validation of success
    redirect_url = None

    if resp.status_code in (301, 302, 303, 307, 308):
        # Standard (non-AJAX) redirect after submit
        location = resp.headers.get("Location", "")
        if "LOGIN" in location.upper():
            return {"status_code": 401, "body": {"error": "Session expired"}}
        if not location:
            return {"status_code": 500, "body": {"success": False, "error": "Empty redirect after submit"}}
        redirect_url = location

    elif resp.status_code == 200:
        # APEX AJAX submit - must return JSON with redirectURL to confirm creation
        try:
            resp_data = resp.json()
        except Exception:
            if "P101_USERNAME" in resp.text or "LOGIN_DESKTOP" in resp.text:
                return {"status_code": 401, "body": {"error": "Session expired"}}
            if "ORA-" in resp.text:
                err_match = re.search(r'(ORA-\d+[^<"]*)', resp.text)
                return {"status_code": 500, "body": {"success": False, "error": err_match.group(1) if err_match else "Database error"}}
            return {"status_code": 500, "body": {"success": False, "error": "Unexpected non-JSON response after submit"}}

        # Check for explicit APEX errors
        if resp_data.get("error"):
            return {"status_code": 400, "body": {"success": False, "error": str(resp_data["error"])}}
        if resp_data.get("errMsg"):
            return {"status_code": 400, "body": {"success": False, "error": str(resp_data["errMsg"])}}

        # Check for APEX validation errors (errors array with message/pageItem)
        apex_errors = resp_data.get("errors", [])
        if apex_errors:
            msgs = [f"{e.get('pageItem', '')}: {e.get('message', '')}" for e in apex_errors]
            return {"status_code": 400, "body": {"success": False, "error": f"Validation failed: {'; '.join(msgs)}"}}

        # Check for field-level validation errors (legacy format)
        item_errors = [i for i in resp_data.get("item", []) if i.get("error")]
        if item_errors:
            msgs = [f"{i.get('id', '')}: {i.get('error', '')}" for i in item_errors]
            return {"status_code": 400, "body": {"success": False, "error": f"Validation failed: {'; '.join(msgs)}"}}

        # Check for notification-type errors
        if resp_data.get("notificationType") == "error":
            return {"status_code": 400, "body": {"success": False, "error": resp_data.get("notification", "Server error")}}

        # Must have redirectURL for confirmed creation
        redirect_url = resp_data.get("redirectURL", "")
        if not redirect_url:
            return {"status_code": 500, "body": {"success": False, "error": "Form submitted but server did not confirm creation (no redirect)"}}

    else:
        if resp.status_code == 401 or "login" in resp.text.lower()[:500]:
            return {"status_code": 401, "body": {"error": "Session expired"}}
        return {"status_code": resp.status_code, "body": {"success": False, "error": f"Submit failed with HTTP {resp.status_code}"}}

    # Build full redirect URL
    if not redirect_url.startswith("http"):
        if redirect_url.startswith("/"):
            redirect_url = f"{base_url}{redirect_url}"
        else:
            redirect_url = f"{base_url}/apex/{redirect_url}"

    # Verify creation via success_msg in redirect URL (APEX encodes it as base64)
    success_msg_match = re.search(r"success_msg=([^&\"' ]+)", redirect_url)
    creation_confirmed = False
    if success_msg_match:
        try:
            raw_b64 = urllib.parse.unquote(success_msg_match.group(1))
            b64_part = raw_b64.split("/")[0] if "/" in raw_b64 else raw_b64
            # Add padding and decode
            padded = b64_part + "=" * (4 - len(b64_part) % 4) if len(b64_part) % 4 else b64_part
            decoded_msg = _b64.b64decode(padded).decode("utf-8", errors="replace")
            if "aangemaakt" in decoded_msg.lower():
                creation_confirmed = True
        except Exception:
            pass

    if not creation_confirmed:
        return {"status_code": 500, "body": {"success": False, "error": "Form submitted but creation was not confirmed by server"}}

    # Extract the internal melding NR from the redirect URL (P411200_NR:{value})
    internal_nr_match = re.search(r'P411200_NR[,:]\s*(\d+)', redirect_url)
    internal_nr = internal_nr_match.group(1) if internal_nr_match else None

    # Follow redirect to detail page to extract the bare VERZOEKNR as fallback
    detail_resp = requests.get(
        redirect_url,
        headers=headers,
        impersonate="chrome131",
        timeout=30,
    )

    fallback_nummer = "unknown"

    if detail_resp.status_code == 200:
        detail_page = detail_resp.text

        if "P101_USERNAME" in detail_page or "LOGIN_DESKTOP" in detail_page:
            return {"status_code": 401, "body": {"error": "Session expired"}}

        # Extract internal NR from page if not found in redirect URL
        if not internal_nr:
            nr_match = re.search(r'id="P411200_NR"[^>]*value="([^"]+)"', detail_page)
            if nr_match:
                internal_nr = nr_match.group(1)

        # Extract bare VERZOEKNR as fallback
        verzoeknr_match = re.search(r'id="P411200_VERZOEKNR"[^>]*value="([^"]+)"', detail_page)
        if verzoeknr_match:
            fallback_nummer = verzoeknr_match.group(1)
        else:
            bc_match = re.search(r'id="P411200_BREADCRUMB_SHORT"[^>]*value="([^"]+)"', detail_page)
            if bc_match:
                bc_val = html_module.unescape(bc_match.group(1))
                nr_from_bc = bc_val.split(" - ")[0].strip() if " - " in bc_val else None
                if nr_from_bc:
                    fallback_nummer = nr_from_bc

    # Look up the full display nummer (e.g., "VVE-13") from the meldingen list report
    display_nummer = _lookup_display_nummer(base_url, headers, p_instance, vves_nr, internal_nr)
    if display_nummer:
        return {"status_code": 200, "body": {"success": True, "nummer": display_nummer}}

    # Fallback to bare VERZOEKNR if list lookup failed
    return {"status_code": 200, "body": {"success": True, "nummer": fallback_nummer}}

def _lookup_display_nummer(base_url, headers, p_instance, vves_nr, internal_nr):
    """Look up the full display nummer (e.g. 'VVE-13') from the meldingen list report.

    Navigates to page 411000, triggers the VERZ report region plugin with the
    VvE filter, and parses the returned HTML table to find the row matching
    the internal NR.  Returns the display nummer string, or None on failure.
    """
    if not internal_nr:
        return None

    try:
        # Step 1: Load page 411000 to get salt and VERZ region ajax identifier
        list_resp = requests.get(
            f"{base_url}/apex/f?p=170:411000::::::",
            headers=headers,
            impersonate="chrome131",
            timeout=30,
            allow_redirects=False,
        )
        if list_resp.status_code in (301, 302, 303, 307, 308):
            location = list_resp.headers.get("Location", "")
            if "LOGIN" in location.upper():
                return None
            if not location.startswith("http"):
                location = f"{base_url}{location}"
            list_resp = requests.get(
                location, headers=headers, impersonate="chrome131", timeout=30
            )
        if list_resp.status_code != 200:
            return None

        list_page = list_resp.text

        if "P101_USERNAME" in list_page or "LOGIN_DESKTOP" in list_page:
            return None

        # Extract salt
        salt_m = re.search(r'value="([^"]*)"[^>]*id="pSalt"', list_page)
        if not salt_m:
            return None
        list_salt = html_module.unescape(salt_m.group(1))

        # Extract protected value
        prot_m = re.search(r'id="pPageItemsProtected"\s+value="([^"]*)"', list_page)
        list_protected = html_module.unescape(prot_m.group(1)) if prot_m else ""

        # Update instance from this page
        ctx_m = re.search(r'value="([^"]*)"[^>]*id="pContext"', list_page)
        if not ctx_m:
            ctx_m = re.search(r'id="pContext"[^>]*value="([^"]*)"', list_page)
        if ctx_m:
            ctx_parts = html_module.unescape(ctx_m.group(1)).split(":")
            if len(ctx_parts) >= 3:
                p_instance = ctx_parts[2]

        # Extract VERZ report region's AJAX identifier
        verz_ajax_m = re.search(
            r'"VERZ","(UkVH[^"]+)"',
            list_page,
        )
        if not verz_ajax_m:
            return None
        verz_ajax_id = verz_ajax_m.group(1).replace("\\u002F", "/")

        # Extract default meldingstatus
        status_m = re.search(
            r'name="P411000_MELDINGSTATUS"[^>]*value="([^"]*)"', list_page
        )
        meldingstatus = status_m.group(1) if status_m else "10:20:30"

        # Step 2: Call the VERZ region PLUGIN to get the meldingen HTML table
        p_json_data = {
            "salt": list_salt,
            "pageItems": {
                "itemsToSubmit": [
                    {"n": "P0_VVE_FILTER", "v": vves_nr},
                    {"n": "P411000_MELDINGSTATUS", "v": meldingstatus},
                    {"n": "P411000_DATUM_VAN", "v": ""},
                    {"n": "P411000_DATUM_TM", "v": ""},
                    {"n": "P411000_TAB_IND_VERZ", "v": "1"},
                    {"n": "P411000_ZOEK", "v": ""},
                    {"n": "P411000_VERZOEKNR_FILTER", "v": ""},
                    {"n": "P411000_MELDER_FILTER", "v": ""},
                    {"n": "P411000_OMSCHRIJVING_KORT_FILTER", "v": ""},
                    {"n": "P411000_VERZ_TYPE_FILTER", "v": ""},
                    {"n": "P411000_BEHANDELAAR_FILTER", "v": ""},
                ],
                "protected": list_protected,
                "rowVersion": "",
                "formRegionChecksums": [],
            },
        }

        plugin_url = f"{base_url}/apex/wwv_flow.ajax?p_context=170:411000:{p_instance}"
        plugin_headers = {
            **headers,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, */*; q=0.01",
            "Referer": f"{base_url}/apex/f?p=170:411000::::::",
            "Origin": base_url,
        }

        plugin_payload = urllib.parse.urlencode({
            "p_flow_id": "170",
            "p_flow_step_id": "411000",
            "p_instance": p_instance,
            "p_debug": "",
            "p_request": f"PLUGIN={verz_ajax_id}",
            "p_widget_action": "reset",
            "x01": "958815183603710210",
            "p_json": json_mod.dumps(p_json_data),
        })

        plugin_resp = requests.post(
            plugin_url,
            headers=plugin_headers,
            data=plugin_payload.encode("utf-8"),
            impersonate="chrome131",
            timeout=30,
        )

        if plugin_resp.status_code != 200:
            return None

        report_html = plugin_resp.text

        # Step 3: Parse the HTML table to find the row with matching internal NR
        # Table format: <td headers="NR"><span class="twinq-report-column">{nr}</span>
        #               <td headers="VERZOEKNR"><span class="twinq-report-column">{display_nummer}</span>
        rows = re.findall(r"<tr>(.*?)</tr>", report_html, re.DOTALL)
        for row in rows:
            nr_m = re.search(
                r'headers="NR"[^>]*><span class="twinq-report-column">([^<]+)</span>',
                row,
            )
            verz_m = re.search(
                r'headers="VERZOEKNR"[^>]*><span class="twinq-report-column">([^<]+)</span>',
                row,
            )
            if nr_m and verz_m and nr_m.group(1).strip() == str(internal_nr):
                return verz_m.group(1).strip()

        return None

    except Exception:
        return None


# === PRIVATE ===
# All API interaction logic is contained within the run() function above.

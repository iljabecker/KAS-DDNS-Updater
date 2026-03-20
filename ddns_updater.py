"""KAS DDNS Updater - Updates ALL-INKL DNS A-Records with current public IP."""

import hashlib
import json
import logging
import os
import sys
import time
from xml.etree import ElementTree

import requests

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("kas-ddns")

KAS_AUTH_URL = "https://kasapi.kasserver.com/soap/KasAuth.php"
KAS_API_URL = "https://kasapi.kasserver.com/soap/KasApi.php"

# IP lookup services (fallback chain)
IP_SERVICES = [
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
    "https://checkip.amazonaws.com",
]


def get_public_ip() -> str:
    """Get current public IPv4 address."""
    for service in IP_SERVICES:
        try:
            resp = requests.get(service, timeout=10)
            resp.raise_for_status()
            ip = resp.text.strip()
            log.debug("Got IP %s from %s", ip, service)
            return ip
        except requests.RequestException as e:
            log.warning("Failed to get IP from %s: %s", service, e)
    raise RuntimeError("Could not determine public IP from any service")


def kas_auth(login: str, password: str) -> str:
    """Authenticate with KAS API and get a session token."""
    # KAS supports sha1 auth: kas_auth_type=sha1, kas_auth_data=sha1(password)
    auth_data = hashlib.sha1(password.encode()).hexdigest()

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KasAuth xmlns="urn:xmethodsKasApi">
      <Params>
        <item>
          <key>kas_login</key>
          <value>{login}</value>
        </item>
        <item>
          <key>kas_auth_type</key>
          <value>sha1</value>
        </item>
        <item>
          <key>kas_auth_data</key>
          <value>{auth_data}</value>
        </item>
      </Params>
    </KasAuth>
  </soap:Body>
</soap:Envelope>"""

    resp = requests.post(
        KAS_AUTH_URL,
        data=soap_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "urn:xmethodsKasApi#KasAuth",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return _parse_auth_token(resp.text)


def _parse_auth_token(xml_text: str) -> str:
    """Extract credential token from KAS auth SOAP response."""
    root = ElementTree.fromstring(xml_text)
    # The token is in the return value of the SOAP response
    for elem in root.iter():
        if elem.tag and "return" in elem.tag.lower():
            if elem.text and len(elem.text) > 10:
                return elem.text.strip()
        # Also check for text content that looks like a token
        if elem.text and len(elem.text.strip()) > 20 and elem.text.strip().isalnum():
            return elem.text.strip()

    # Fallback: search all text nodes
    all_text = []
    for elem in root.iter():
        if elem.text and elem.text.strip():
            all_text.append(elem.text.strip())

    # The token is usually the longest alphanumeric string
    candidates = [t for t in all_text if len(t) > 20]
    if candidates:
        return max(candidates, key=len)

    raise RuntimeError(f"Could not parse auth token from response: {xml_text[:500]}")


def kas_api_call(token: str, login: str, action: str, params: dict | None = None) -> str:
    """Make a KAS API SOAP call using session token auth."""
    params_xml = ""
    if params:
        for key, value in params.items():
            params_xml += f"""
          <item>
            <key>{key}</key>
            <value>{value}</value>
          </item>"""

    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KasApi xmlns="urn:xmethodsKasApi">
      <Params>
        <item>
          <key>kas_login</key>
          <value>{login}</value>
        </item>
        <item>
          <key>kas_auth_type</key>
          <value>session</value>
        </item>
        <item>
          <key>kas_auth_data</key>
          <value>{token}</value>
        </item>
        <item>
          <key>kas_action</key>
          <value>{action}</value>
        </item>
        <item>
          <key>kas_action_params</key>
          <value>{params_xml}
          </value>
        </item>
      </Params>
    </KasApi>
  </soap:Body>
</soap:Envelope>"""

    resp = requests.post(
        KAS_API_URL,
        data=soap_body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": "urn:xmethodsKasApi#KasApi",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_dns_records(xml_text: str) -> list[dict]:
    """Parse DNS records from KAS API SOAP response."""
    records = []
    root = ElementTree.fromstring(xml_text)

    current_record = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

        if tag == "key" and elem.text:
            key = elem.text.strip()
        elif tag == "value" and elem.text:
            value = elem.text.strip()
            if "key" in dir() and key:
                current_record[key] = value
                if key == "record_aux":
                    records.append(current_record)
                    current_record = {}
                key = None

    # Fallback: try to find records by looking for record_id patterns
    if not records:
        log.debug("Primary parsing found no records, trying fallback parser")
        records = _fallback_parse_records(xml_text)

    return records


def _fallback_parse_records(xml_text: str) -> list[dict]:
    """Fallback parser that extracts DNS records from SOAP response."""
    records = []
    root = ElementTree.fromstring(xml_text)

    # Collect all key-value pairs
    all_items = []
    for elem in root.iter():
        children = list(elem)
        if len(children) == 2:
            tags = [c.tag.split("}")[-1] if "}" in c.tag else c.tag for c in children]
            if tags == ["key", "value"]:
                k = children[0].text.strip() if children[0].text else ""
                v = children[1].text.strip() if children[1].text else ""
                all_items.append((k, v))

    # Group into records (each record starts with record_id)
    current = {}
    for k, v in all_items:
        if k == "record_id" and current:
            records.append(current)
            current = {}
        if k.startswith("record_") or k in ("zone_host",):
            current[k] = v
    if current and "record_id" in current:
        records.append(current)

    return records


def get_dns_records(token: str, login: str, zone: str) -> list[dict]:
    """Get all DNS records for a zone."""
    xml = kas_api_call(token, login, "get_dns_settings", {"zone_host": zone})
    return parse_dns_records(xml)


def update_dns_record(token: str, login: str, record_id: str, new_ip: str) -> bool:
    """Update a DNS record's data (IP address)."""
    xml = kas_api_call(
        token, login, "update_dns_settings",
        {"record_id": record_id, "record_data": new_ip},
    )
    log.debug("Update response: %s", xml[:500])
    return "true" in xml.lower() or "fault" not in xml.lower()


def run_update():
    """Main update logic."""
    login = os.environ.get("KAS_LOGIN")
    password = os.environ.get("KAS_PASSWORD")
    domains = os.environ.get("KAS_DOMAINS", "")  # comma-separated: "example.com,sub.example.com"
    record_names = os.environ.get("KAS_RECORD_NAMES", "")  # optional: specific record names to update

    if not login or not password or not domains:
        log.error("Missing required env vars: KAS_LOGIN, KAS_PASSWORD, KAS_DOMAINS")
        sys.exit(1)

    domain_list = [d.strip() for d in domains.split(",") if d.strip()]
    record_name_list = [r.strip() for r in record_names.split(",") if r.strip()] if record_names else []

    # Get current public IP
    current_ip = get_public_ip()
    log.info("Current public IP: %s", current_ip)

    # Authenticate
    log.info("Authenticating with KAS API as %s...", login)
    token = kas_auth(login, password)
    log.info("Authentication successful")

    for domain in domain_list:
        # Extract zone (top-level domain)
        parts = domain.split(".")
        if len(parts) >= 2:
            zone = ".".join(parts[-2:]) + "."
        else:
            zone = domain + "."

        log.info("Processing domain: %s (zone: %s)", domain, zone)

        # Respect KAS flood protection
        time.sleep(3)

        # Get current DNS records
        records = get_dns_records(token, login, zone)
        log.info("Found %d DNS records for zone %s", len(records), zone)

        # Find matching A records
        updated = 0
        for record in records:
            record_type = record.get("record_type", "")
            record_name = record.get("record_name", "")
            record_data = record.get("record_data", "")
            record_id = record.get("record_id", "")

            if record_type != "A":
                continue

            # Check if this record matches what we want to update
            should_update = False
            if record_name_list:
                # Only update specified record names
                if record_name in record_name_list:
                    should_update = True
            else:
                # Update all A records in the zone that belong to our domains
                full_name = record_name + zone if record_name else zone.rstrip(".")
                for d in domain_list:
                    if d.rstrip(".") in full_name or record_name == "" or record_name == domain.split(".")[0]:
                        should_update = True
                        break

            if not should_update:
                continue

            if record_data == current_ip:
                log.info("  Record %s (ID: %s) already points to %s - skipping",
                         record_name or "@", record_id, current_ip)
                continue

            log.info("  Updating record %s (ID: %s): %s -> %s",
                     record_name or "@", record_id, record_data, current_ip)

            time.sleep(3)  # KAS flood protection
            success = update_dns_record(token, login, record_id, current_ip)
            if success:
                log.info("  Successfully updated record %s", record_name or "@")
                updated += 1
            else:
                log.error("  Failed to update record %s", record_name or "@")

        if updated == 0:
            log.info("No records needed updating for %s", domain)
        else:
            log.info("Updated %d record(s) for %s", updated, domain)

    log.info("DDNS update cycle complete")


def main():
    """Entry point with scheduling support."""
    interval = int(os.environ.get("UPDATE_INTERVAL", "300"))  # default: 5 minutes

    log.info("KAS DDNS Updater starting")
    log.info("Update interval: %d seconds", interval)

    while True:
        try:
            run_update()
        except Exception:
            log.exception("Error during update cycle")

        log.info("Next update in %d seconds...", interval)
        time.sleep(interval)


if __name__ == "__main__":
    main()

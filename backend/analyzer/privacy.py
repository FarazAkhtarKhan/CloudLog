"""
Privacy filter: masks personal data that leaks into free-text log messages
before anything is written to the cloud database.

Structured fields (service, ip_address, ...) are governed by the log contract;
the message body is arbitrary text, so it is the place PII usually slips in.
"""
import re

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,15}(\d{4})\b")
_IPV4 = re.compile(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}\b")


def redact(text: str) -> tuple[str, bool]:
    """Return (masked_text, changed). Emails, card numbers and IPv4 hosts are masked."""
    masked = _EMAIL.sub(r"\1***@\2", text)
    masked = _CARD.sub(r"****-****-****-\1", masked)
    masked = _IPV4.sub(r"\1.x", masked)
    return masked, masked != text


def mask_ip(ip: str) -> str:
    """192.168.1.45 -> 192.168.1.x (keeps the subnet for correlation)."""
    return _IPV4.sub(r"\1.x", ip)

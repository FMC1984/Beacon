"""Outbound email seam. With no provider configured nothing is sent and the
caller shows the link instead; every call reports which of those happened."""

from dataclasses import dataclass

import httpx

from app.config import settings


@dataclass
class EmailResult:
    delivered: bool
    reason: str


def send_email(to: str, subject: str, body: str) -> EmailResult:
    provider = settings.email_provider.strip().lower()
    if not provider:
        return EmailResult(False, "No email provider is configured; pass the link on by hand.")
    if provider == "resend":
        if not settings.email_api_key or not settings.email_from:
            return EmailResult(False, "Resend needs CITEROLL_EMAIL_API_KEY and CITEROLL_EMAIL_FROM.")
        try:
            r = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.email_api_key}"},
                json={"from": settings.email_from, "to": [to], "subject": subject, "text": body},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            return EmailResult(False, f"Email provider unreachable: {exc}")
        if r.status_code >= 300:
            return EmailResult(False, f"Email provider refused the message (HTTP {r.status_code}).")
        return EmailResult(True, "Sent.")
    return EmailResult(False, f"Unknown email provider {provider!r}.")

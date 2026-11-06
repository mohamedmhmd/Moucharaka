"""Test helper: sign the contract a client was just sent to, as a member would (dev-mode code)."""
from .models import Contract


def sign_pending(client, user, accept=True):
    contract = Contract.objects.filter(created_by=user, status=Contract.Status.PENDING).latest("created_at")
    code = client.session.get(f"sign_code_{contract.reference}")
    data = {"action": "sign", "code": code}
    if accept:
        data["accept"] = "1"
    response = client.post(f"/fr/contracts/{contract.reference}/sign/", data)
    contract.refresh_from_db()
    return contract, response

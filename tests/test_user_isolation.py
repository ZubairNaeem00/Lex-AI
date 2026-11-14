"""Cross-account isolation.

The rule under test: identity comes from the access token only. Every read and
write must stay inside the caller's rows, and another account's ids must look
exactly like ids that do not exist.
"""

from __future__ import annotations

from conftest import auth_header

from db import crud


def as_client(client, account):
    return auth_header(account["token"])


def make_case(client, account, name):
    response = client.post("/api/cases", headers=auth_header(account["token"]),
                           json={"name": name})
    assert response.status_code == 201
    return response.json()["case"]


def test_second_account_sees_none_of_the_firsts_data(client, account_a, account_b):
    make_case(client, account_a, "Case of advocate A")
    make_case(client, account_a, "Another case of advocate A")

    listing = client.get("/api/cases", headers=as_client(client, account_b))
    assert listing.json()["total"] == 0
    assert listing.json()["items"] == []

    stats = client.get("/api/users/me/summary", headers=as_client(client, account_b))
    assert stats.json()["counts"]["cases"] == 0


def test_another_users_case_id_reads_as_missing(client, account_a, account_b):
    case = make_case(client, account_a, "Sealed file")
    headers_b = as_client(client, account_b)

    assert client.get(f"/api/cases/{case['id']}", headers=headers_b).status_code == 404
    assert client.patch(f"/api/cases/{case['id']}", headers=headers_b,
                        json={"name": "hijacked"}).status_code == 404
    assert client.delete(f"/api/cases/{case['id']}", headers=headers_b).status_code == 404
    assert client.get(f"/api/cases/{case['id']}/summary", headers=headers_b).status_code == 404
    assert client.get(f"/api/cases/{case['id']}/facts", headers=headers_b).status_code == 404

    assert crud.cases.get(case["id"])["name"] == "Sealed file"


def test_caseless_chat_is_not_mixed_between_accounts(client, account_a, account_b):
    for account in (account_a, account_b):
        conversation = client.post("/api/conversations", headers=as_client(client, account),
                                   json={"title": "General", "type": "general"}).json()
        client.post(f"/api/conversations/{conversation['id']}/messages",
                    headers=as_client(client, account),
                    json={"role": "user", "content": f"question from {account['email']}"})

    listing = client.get("/api/conversations?unassigned=true", headers=as_client(client, account_b))
    assert listing.json()["total"] == 1
    mine = listing.json()["items"][0]
    assert mine["user_id"] == account_b["id"]

    transcript = client.get(f"/api/conversations/{mine['id']}/messages",
                            headers=as_client(client, account_b))
    assert account_b["email"] in transcript.json()["items"][0]["content"]

    other = client.get("/api/conversations", headers=as_client(client, account_a))
    other_id = other.json()["items"][0]["id"]
    other_transcript = client.get(f"/api/conversations/{other_id}/messages",
                                  headers=as_client(client, account_b))
    assert other_transcript.status_code == 404


def test_documents_and_analyses_are_private(client, account_a, account_b):
    case = make_case(client, account_a, "Evidence bundle")
    owner = crud.to_oid(account_a["id"])
    upload_id = crud.documents.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "runtime_case_id": case["runtime_case_id"], "runtime_document_id": "doc_priv",
        "filename": "secret-fir.pdf", "status": "analyzed", "archived": False,
    })
    crud.analyses.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "document_id": crud.to_oid(upload_id, "document_id"),
        "extracted_text": "confidential text", "report": {}, "original_report": {},
        "edits": [], "status": "complete", "version": 1,
    })

    headers_b = as_client(client, account_b)
    assert client.get(f"/api/documents/{upload_id}", headers=headers_b).status_code == 404
    assert client.get(f"/api/documents/{upload_id}/transcript", headers=headers_b).status_code == 404
    assert client.get(f"/api/documents/{upload_id}/file", headers=headers_b).status_code == 404
    assert client.get(f"/api/documents?case_id={case['id']}", headers=headers_b).status_code == 404
    assert client.get("/api/documents", headers=headers_b).json()["total"] == 0


def test_generation_state_and_files_are_private(client, account_a, account_b):
    case = make_case(client, account_a, "Drafting matter")
    owner = crud.to_oid(account_a["id"])
    session_id = crud.generation_sessions.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "session_key": "gen_private", "template_name": "bail_petition",
        "status": "collecting", "workflow_state": {"id": "gen_private"},
    })
    generated_id = crud.generated_documents.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "generation_session_id": crud.to_oid(session_id, "generation_session_id"),
        "runtime_document_id": "gen_doc_private", "template_name": "bail_petition",
        "filename": "private.docx", "file_path": "", "status": "generated",
    })

    headers_b = as_client(client, account_b)
    assert client.get("/api/generation/sessions/gen_private", headers=headers_b).status_code == 404
    assert client.get(f"/api/generation/documents/{generated_id}/download",
                      headers=headers_b).status_code == 404
    assert client.get("/api/generation/sessions", headers=headers_b).json()["total"] == 0
    assert client.get("/api/generation/documents", headers=headers_b).json()["total"] == 0


def test_client_supplied_user_id_is_ignored(client, account_a, account_b):
    """A body or query cannot claim another account, even with a valid token."""
    headers_a = as_client(client, account_a)
    spoofed = client.post("/api/cases", headers=headers_a,
                          json={"name": "Not mine", "user_id": str(account_b["id"])})
    assert spoofed.status_code == 422, "unknown fields must be rejected outright"

    case = make_case(client, account_a, "Mine")
    assert str(crud.cases.get(case["id"])["user_id"]) == account_a["id"]

    conversation = client.post("/api/conversations", headers=as_client(client, account_b),
                               json={"title": "Probe", "case_id": case["id"]})
    assert conversation.status_code == 404, "case_id must belong to the caller"


def test_tokens_cannot_be_replayed_after_account_disabled(client, account_a):
    crud.users.set_by_id(account_a["id"], {"status": "disabled"})
    assert client.get("/api/users/me",
                      headers=as_client(client, account_a)).status_code == 403


def test_activity_logs_are_scoped_per_account(client, account_a, account_b):
    make_case(client, account_a, "Audited matter")
    client.get("/api/activity", headers=as_client(client, account_b))
    listing = client.get("/api/activity", headers=as_client(client, account_b))
    assert listing.json()["total"] >= 1
    assert all(str(row["user_id"]) == account_b["id"] for row in listing.json()["items"])

    other_id = crud.activity_logs.find({"user_id": account_a["id"]})[0]["_id"]
    detail = client.get("/api/activity", headers=as_client(client, account_b))
    assert all(row["id"] != str(other_id) for row in detail.json()["items"])


def test_permanent_case_delete_only_removes_own_rows(client, account_a, account_b):
    mine = make_case(client, account_a, "Delete me")
    theirs = make_case(client, account_b, "Keep me")

    forbidden = client.delete(f"/api/cases/{theirs['id']}?permanent=true",
                             headers=as_client(client, account_a))
    assert forbidden.status_code == 404
    assert crud.cases.get(theirs["id"]) is not None

    removed = client.delete(f"/api/cases/{mine['id']}?permanent=true",
                            headers=as_client(client, account_a))
    assert removed.json()["permanent"] is True
    assert crud.cases.get(mine["id"]) is None
    assert crud.cases.get(theirs["id"]) is not None

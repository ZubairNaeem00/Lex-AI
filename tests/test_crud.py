"""CRUD over the case / conversation / document / drafting collections."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import auth_header

from db import crud

SAMPLE_REPORT = {
    "document_type": "First Information Report",
    "title": "FIR 41/2022",
    "sections": [
        {"title": "Parties", "fields": [
            {"label": "Complainant", "value": "Ahmed Raza"},
            {"label": "Accused", "value": "Unknown person"},
        ]},
        {"title": "Offence", "fields": [
            {"label": "Offence description", "value": "Theft of a mobile phone"},
        ]},
    ],
}


def create_case(client, account, name="Bail petition — District Sessions"):
    response = client.post("/api/cases", headers=auth_header(account["token"]),
                           json={"name": name, "case_type": "bail",
                                 "description": "Arrest under s.420 PPC."})
    assert response.status_code == 201, response.text
    return response.json()


def test_case_crud_round_trip(client, account_a):
    headers = auth_header(account_a["token"])

    created = create_case(client, account_a)
    case_id = created["case"]["id"]
    assert created["runtime_case_id"].startswith("case_")
    assert created["case"]["case_type"] == "bail"

    fetched = client.get(f"/api/cases/{case_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["name"].startswith("Bail petition")

    listed = client.get("/api/cases", headers=headers)
    assert listed.json()["total"] == 1

    renamed = client.patch(f"/api/cases/{case_id}", headers=headers,
                           json={"status": "in_progress", "court": "Lahore"})
    assert renamed.json()["status"] == "in_progress"
    assert renamed.json()["court"] == "Lahore"

    empty_update = client.patch(f"/api/cases/{case_id}", headers=headers, json={})
    assert empty_update.status_code == 400

    archived = client.delete(f"/api/cases/{case_id}", headers=headers)
    assert archived.json()["permanent"] is False
    assert client.get(f"/api/cases/{case_id}", headers=headers).json()["archived"] is True
    assert crud.messages.count({}) == 0


def test_case_search_and_pagination(client, account_a):
    headers = auth_header(account_a["token"])
    for index in range(3):
        create_case(client, account_a, name=f"Matter number {index}")

    page = client.get("/api/cases?page_size=2", headers=headers)
    assert page.json()["total"] == 4
    assert len(page.json()["items"]) == 2
    assert page.json()["has_more"] is True

    search = client.get("/api/cases?search=Matter%20number%202", headers=headers)
    assert search.json()["total"] == 1

    bad_page = client.get("/api/cases?page_size=500", headers=headers)
    assert bad_page.status_code == 422


def test_conversation_crud_with_messages_and_memory(client, account_a):
    headers = auth_header(account_a["token"])
    case = create_case(client, account_a)["case"]

    conversation = client.post("/api/conversations", headers=headers,
                               json={"title": "Bail hearing prep", "case_id": case["id"]})
    assert conversation.status_code == 201
    conversation_id = conversation.json()["id"]
    assert conversation.json()["type"] == "case"
    assert conversation.json()["case_id"] == case["id"]

    for index in range(3):
        appended = client.post(f"/api/conversations/{conversation_id}/messages", headers=headers,
                               json={"role": "user", "content": f"Question number {index}"})
        assert appended.status_code == 201

    transcript = client.get(f"/api/conversations/{conversation_id}/messages", headers=headers)
    assert transcript.json()["total"] == 3
    assert [item["content"] for item in transcript.json()["items"]][0] == "Question number 0"

    memory = client.put(f"/api/conversations/{conversation_id}/memory", headers=headers,
                        json={"summary": "User is preparing a bail application.",
                              "key_facts": ["arrested on 12 March"],
                              "open_questions": ["is surety available?"],
                              "message_count": 3})
    assert memory.status_code == 200
    assert memory.json()["version"] == 1

    stored = client.get(f"/api/conversations/{conversation_id}/memory", headers=headers)
    assert stored.json()["key_facts"] == ["arrested on 12 March"]

    listing = client.get(f"/api/conversations?case_id={case['id']}", headers=headers)
    assert listing.json()["total"] == 1


def test_case_less_general_conversation(client, account_a):
    headers = auth_header(account_a["token"])
    created = client.post("/api/conversations", headers=headers,
                          json={"title": "Khula question", "type": "general"})
    assert created.status_code == 201
    assert created.json()["case_id"] is None
    assert created.json()["type"] == "general"

    client.post(f"/api/conversations/{created.json()['id']}/messages", headers=headers,
                json={"role": "user", "content": "What is khula?"})

    unassigned = client.get("/api/conversations?unassigned=true", headers=headers)
    assert unassigned.json()["total"] == 1


def test_deleting_a_conversation_archives_by_default(client, account_a):
    headers = auth_header(account_a["token"])
    conversation = client.post("/api/conversations", headers=headers,
                               json={"title": "Temporary chat"})
    conversation_id = conversation.json()["id"]
    client.post(f"/api/conversations/{conversation_id}/messages", headers=headers,
                json={"role": "assistant", "content": "Answer"})

    archived = client.delete(f"/api/conversations/{conversation_id}", headers=headers)
    assert archived.json()["permanent"] is False
    assert crud.messages.count({"conversation_id": conversation_id}) == 1

    removed = client.delete(f"/api/conversations/{conversation_id}?permanent=true",
                           headers=headers)
    assert removed.json()["permanent"] is True
    assert crud.messages.count({"conversation_id": conversation_id}) == 0


def test_document_and_analysis_records_are_reachable(client, account_a):
    headers = auth_header(account_a["token"])
    case = create_case(client, account_a)["case"]
    owner = crud.to_oid(account_a["id"])

    upload_id = crud.documents.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "runtime_case_id": case["runtime_case_id"],
        "runtime_document_id": "doc_probe1", "filename": "FIR.pdf",
        "content_type": "application/pdf", "size_bytes": 1234,
        "sha256": "abc", "status": "analyzed",
    })
    analysis_id = crud.analyses.insert({
        "user_id": owner, "case_id": crud.to_oid(case["id"], "case_id"),
        "document_id": crud.to_oid(upload_id, "document_id"),
        "extracted_text": "Complainant: Ahmed Raza", "report": SAMPLE_REPORT,
        "original_report": SAMPLE_REPORT, "edits": [], "status": "complete", "version": 1,
    })

    listed = client.get(f"/api/documents?case_id={case['id']}", headers=headers)
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["filename"] == "FIR.pdf"

    analysis = client.get(f"/api/documents/{upload_id}/analysis", headers=headers)
    assert analysis.status_code == 200
    assert analysis.json()["report"]["document_type"] == "First Information Report"
    assert analysis.json()["extracted_characters"] == len("Complainant: Ahmed Raza")

    transcript = client.get(f"/api/documents/{upload_id}/transcript", headers=headers)
    assert transcript.json()["extracted_text"].startswith("Complainant")
    assert transcript.json()["filename"] == "FIR.pdf"
    assert analysis_id

    missing_file = client.get(f"/api/documents/{upload_id}/file", headers=headers)
    assert missing_file.status_code == 404


def test_case_facts_upsert_and_delete(client, account_a):
    headers = auth_header(account_a["token"])
    case = create_case(client, account_a)["case"]

    written = client.post(f"/api/cases/{case['id']}/facts", headers=headers,
                          json={"facts": [
                              {"field_name": "applicants_full_name", "field_value": "Ali Khan"},
                              {"field_name": "police_station", "field_value": "Model Town"},
                          ]})
    assert written.status_code == 201
    assert written.json()["written"] == 2

    corrected = client.post(f"/api/cases/{case['id']}/facts", headers=headers,
                            json={"facts": [
                                {"field_name": "applicants_full_name",
                                 "field_value": "Ali Hassan Khan", "source": "user",
                                 "corrected": True}]})
    names = {item["field_name"]: item for item in corrected.json()["items"]}
    assert names["applicants_full_name"]["field_value"] == "Ali Hassan Khan"
    assert names["applicants_full_name"]["corrected"] is True
    assert len(names) == 2, "upsert must not duplicate a field"

    listing = client.get(f"/api/cases/{case['id']}/facts", headers=headers)
    assert listing.json()["total"] == 2

    fact_id = names["police_station"]["id"]
    removed = client.delete(f"/api/cases/{case['id']}/facts/{fact_id}", headers=headers)
    assert removed.json()["ok"] is True
    assert client.get(f"/api/cases/{case['id']}/facts", headers=headers).json()["total"] == 1


def test_generation_sessions_and_documents_listing(client, account_a):
    headers = auth_header(account_a["token"])
    case = create_case(client, account_a)["case"]
    owner = crud.to_oid(account_a["id"])
    case_oid = crud.to_oid(case["id"], "case_id")

    session_id = crud.generation_sessions.insert({
        "user_id": owner, "case_id": case_oid, "session_key": "gen_probe1",
        "document_type": "Bail Application", "template_name": "bail_petition",
        "current_step": "court_name",
        "collected_information": {"applicants_full_name": "Ali Khan"},
        "missing_fields": ["court_name"], "status": "collecting",
        "workflow_state": {"id": "gen_probe1", "status": "collecting",
                           "values": {"applicants_full_name": "Ali Khan"}},
    })
    document_id = crud.generated_documents.insert({
        "user_id": owner, "case_id": case_oid, "runtime_document_id": "gen_doc_probe",
        "generation_session_id": crud.to_oid(session_id, "generation_session_id"),
        "document_type": "bail_petition", "template_name": "bail_petition",
        "filename": "bail.docx", "file_path": "", "download_url": "",
        "values": {"applicants_full_name": "Ali Khan"}, "status": "generated",
    })

    sessions = client.get("/api/generation/sessions", headers=headers)
    assert sessions.json()["total"] == 1
    assert sessions.json()["items"][0]["session_key"] == "gen_probe1"
    assert "workflow_state" not in sessions.json()["items"][0]

    one = client.get("/api/generation/sessions/gen_probe1", headers=headers)
    assert one.status_code == 200
    assert one.json()["missing_fields"] == ["court_name"]

    documents = client.get(f"/api/generation/documents?case_id={case['id']}", headers=headers)
    assert documents.json()["total"] == 1

    download = client.get(f"/api/generation/documents/{document_id}/download", headers=headers)
    assert download.status_code == 404, "a missing file must not be served"

    summary = client.get(f"/api/cases/{case['id']}/summary", headers=headers)
    assert summary.json()["counts"]["generations"] == 1
    assert summary.json()["counts"]["generated_documents"] == 1


def test_activity_and_notifications(client, account_a):
    headers = auth_header(account_a["token"])

    activity = client.get("/api/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.json()["total"] >= 1

    created = client.post("/api/notifications", headers=headers,
                          json={"title": "Hearing reminder", "message": "file by Friday",
                                "kind": "deadline"})
    assert created.status_code == 201
    notification_id = created.json()["id"]

    unread = client.get("/api/notifications?unread_only=true", headers=headers)
    assert unread.json()["total"] == 1
    assert unread.json()["unread"] == 1

    read = client.patch(f"/api/notifications/{notification_id}/read", headers=headers)
    assert read.json()["read"] is True
    assert client.get("/api/notifications?unread_only=true", headers=headers).json()["unread"] == 0

    assert client.delete(f"/api/notifications/{notification_id}", headers=headers).json() == {
        "ok": True}


def test_users_summary_endpoint(client, account_a):
    headers = auth_header(account_a["token"])
    create_case(client, account_a)
    summary = client.get("/api/users/me/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["counts"]["cases"] == 1
    assert summary.json()["database"]["connected"] is True


def test_objectid_relationships_are_real_references(client, account_a):
    headers = auth_header(account_a["token"])
    case = create_case(client, account_a)["case"]
    conversation = client.post("/api/conversations", headers=headers,
                               json={"title": "Refs", "case_id": case["id"]}).json()
    client.post(f"/api/conversations/{conversation['id']}/messages", headers=headers,
                json={"role": "user", "content": "hello"})

    message = crud.messages.find({})[0]
    assert isinstance(message["user_id"], crud.ObjectId)
    assert isinstance(message["conversation_id"], crud.ObjectId)
    assert str(message["case_id"]) == case["id"]
    assert message["created_at"].tzinfo is not None


def test_timestamps_are_stored_as_datetimes(client, account_a):
    case = create_case(client, account_a)["case"]
    stored = crud.cases.get(case["id"])
    assert isinstance(stored["created_at"], datetime)
    assert stored["created_at"].tzinfo is not None

    session_row = crud.user_sessions.find_one({"user_id": account_a["id"]})
    assert session_row["expires_at"] > datetime.now(timezone.utc) + timedelta(days=29)

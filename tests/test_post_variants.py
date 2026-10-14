from datetime import UTC, datetime

import pytest
from socialdock.models import MediaAsset


@pytest.fixture()
def media_id(session):
    asset = MediaAsset(stored_path="test.mp4", original_name="test.mp4", display_name="test", sha256="test")
    session.add(asset)
    session.commit()
    return asset.id


@pytest.fixture()
def accounts(client):
    return client.post("/api/accounts/demo/seed").json()


def variants_for(accounts, shape):
    variants = {}
    expected = {}
    for account in accounts:
        platform = account["platform"]
        field = "description" if platform == "youtube" else "caption"
        legacy = shape == "legacy" or (shape == "mixed" and platform == "youtube")
        text = f"Texte {platform}" if legacy else f"Texte {account['id']}"
        expected[account["id"]] = (field, text)
        if legacy:
            variants[platform] = {field: text, "metadata": {"source": "legacy"}}
        else:
            variants.setdefault(platform, {})[account["id"]] = {field: text}
    return variants, expected


def assert_variants(post, expected):
    assert len(post["targets"]) == len(expected)
    for target in post["targets"]:
        field, text = expected[target["account_id"]]
        assert target["payload"][field] == text
        assert not any(account_id in target["payload"] for account_id in expected)


@pytest.mark.parametrize("shape", ["legacy", "accounts", "mixed"])
def test_create_accepts_both_variant_formats(client, accounts, shape):
    variants, expected = variants_for(accounts, shape)
    response = client.post("/api/posts", json={
        "title": "Variantes", "account_ids": [a["id"] for a in accounts], "per_platform": variants,
    })
    assert response.status_code == 201, response.text
    post = response.json()
    assert_variants(post, expected)
    assert_variants(client.get(f"/api/posts/{post['id']}").json(), expected)


@pytest.mark.parametrize("shape", ["legacy", "accounts", "mixed"])
def test_patch_variants_without_account_ids(client, accounts, shape):
    post = client.post("/api/posts", json={"title": "Avant", "account_ids": [a["id"] for a in accounts]}).json()
    variants, expected = variants_for(accounts, shape)
    response = client.patch(f"/api/posts/{post['id']}", json={"per_platform": variants})
    assert response.status_code == 200, response.text
    assert_variants(response.json(), expected)
    assert_variants(client.get(f"/api/posts/{post['id']}").json(), expected)


def test_patch_only_changes_the_requested_account(client, accounts):
    variants, expected = variants_for(accounts, "accounts")
    post = client.post("/api/posts", json={
        "title": "Partiel", "account_ids": [a["id"] for a in accounts], "per_platform": variants,
    }).json()
    account = next(a for a in accounts if a["platform"] == "tiktok")
    response = client.patch(f"/api/posts/{post['id']}", json={
        "per_platform": {"tiktok": {account["id"]: {"caption": "Modifié"}}},
    })
    assert response.status_code == 200
    expected[account["id"]] = ("caption", "Modifié")
    assert_variants(response.json(), expected)


def test_patch_replaces_the_selected_accounts(client, accounts):
    variants, expected = variants_for(accounts[:2], "accounts")
    post = client.post("/api/posts", json={
        "title": "Comptes", "account_ids": [a["id"] for a in accounts[:2]], "per_platform": variants,
    }).json()
    selected = [accounts[1], accounts[2]]
    variants, expected = variants_for(selected, "accounts")
    response = client.patch(f"/api/posts/{post['id']}", json={
        "account_ids": [a["id"] for a in selected], "per_platform": variants,
    })
    assert response.status_code == 200, response.text
    assert_variants(response.json(), expected)
    assert_variants(client.get(f"/api/posts/{post['id']}").json(), expected)


@pytest.mark.parametrize("shape", ["legacy", "accounts", "mixed"])
def test_batch_accepts_both_variant_formats(client, accounts, media_id, shape):
    variants, expected = variants_for(accounts, shape)
    response = client.post("/api/posts/batch-schedule", json={
        "media_ids": [media_id], "account_ids": [a["id"] for a in accounts],
        "days": ["2027-07-15"], "times": ["09:30"], "per_platform": variants,
    })
    assert response.status_code == 200, response.text
    post_id = response.json()["scheduled"][0]["post_id"]
    assert_variants(client.get(f"/api/posts/{post_id}").json(), expected)


@pytest.mark.parametrize("shape", ["legacy", "accounts"])
def test_apply_template_restores_each_accounts_variant(client, accounts, shape):
    variants, expected = variants_for(accounts, shape)
    source = client.post("/api/posts", json={
        "title": "Source", "description": "Commun", "hashtags": ["original"],
        "account_ids": [a["id"] for a in accounts], "per_platform": variants,
    })
    assert source.status_code == 201, source.text
    template_body = {"name": "Modèle", "from_post_id": source.json()["id"]} if shape == "accounts" else {
        "name": "Ancien modèle", "payload": {"description": "Commun", "per_platform": variants},
    }
    template = client.post("/api/posts/templates", json=template_body).json()
    target = client.post("/api/posts", json={"title": "Destination", "account_ids": [a["id"] for a in accounts]}).json()
    response = client.post(f"/api/posts/{target['id']}/template", params={"template_id": template["id"]})
    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Commun"
    assert_variants(response.json(), expected)


def test_batch_explicit_variants_override_template(client, accounts, media_id):
    variants, expected = variants_for(accounts, "accounts")
    template = client.post("/api/posts/templates", json={
        "name": "Lot", "payload": {"description": "Modèle", "per_platform": {"tiktok": {"caption": "Modèle TikTok"}}},
    }).json()
    response = client.post("/api/posts/batch-schedule", json={
        "media_ids": [media_id], "account_ids": [a["id"] for a in accounts],
        "days": ["2027-07-15"], "times": ["09:30"], "template_id": template["id"], "per_platform": variants,
    })
    assert response.status_code == 200, response.text
    post_id = response.json()["scheduled"][0]["post_id"]
    assert_variants(client.get(f"/api/posts/{post_id}").json(), expected)


@pytest.mark.parametrize("day,utc", [("2027-01-15", "2027-01-15T08:30:00+00:00"), ("2027-07-15", "2027-07-15T07:30:00+00:00")])
def test_batch_converts_paris_slots_to_utc(client, accounts, media_id, day, utc):
    response = client.post("/api/posts/batch-schedule", json={
        "media_ids": [media_id], "account_ids": [accounts[0]["id"]], "days": [day], "times": ["09:30"],
    })
    assert response.status_code == 200
    slot = response.json()["scheduled"][0]
    assert slot["scheduled_at"] == utc
    post = client.get(f"/api/posts/{slot['post_id']}").json()
    moment = datetime.fromisoformat(post["targets"][0]["scheduled_at"].replace("Z", "+00:00"))
    assert moment.astimezone(UTC) == datetime.fromisoformat(utc)


def test_batch_rejects_nonexistent_paris_time(client, accounts, media_id):
    response = client.post("/api/posts/batch-schedule", json={
        "media_ids": [media_id], "account_ids": [accounts[0]["id"]], "days": ["2027-03-28"], "times": ["02:30"],
    })
    assert response.status_code == 400


def test_batch_uses_first_occurrence_of_ambiguous_paris_time(client, accounts, media_id):
    response = client.post("/api/posts/batch-schedule", json={
        "media_ids": [media_id], "account_ids": [accounts[0]["id"]], "days": ["2027-10-31"], "times": ["02:30"],
    })
    assert response.status_code == 200
    assert response.json()["scheduled"][0]["scheduled_at"] == "2027-10-31T00:30:00+00:00"


def test_calendar_uses_paris_day_boundaries(client, accounts):
    post = client.post("/api/posts", json={"title": "Minuit Paris", "account_ids": [accounts[0]["id"]]}).json()
    target_id = post["targets"][0]["id"]
    response = client.post(f"/api/posts/targets/{target_id}/schedule", json={"scheduled_at": "2027-07-15T22:30:00Z"})
    assert response.status_code == 200
    day = client.get("/api/calendar", params={"start": "2027-07-16", "end": "2027-07-16"}).json()
    assert len(day["items"]) == 1
    entry = day["items"][0]
    assert entry["scheduled_at"] == "2027-07-15T22:30:00+00:00"
    assert day["by_day"] == {"2027-07-16": [entry]}
    previous = client.get("/api/calendar", params={"start": "2027-07-15", "end": "2027-07-15"}).json()
    assert previous["items"] == []
    queue = client.get("/api/calendar/queue").json()
    assert queue["items"][0]["scheduled_at"] == "2027-07-15T22:30:00+00:00"

"""
T8 image integration tests (spec docs/plans/t8-images.md §4.14).

Runs against the live Docker stack, like the rest of this suite. Covers prompt and
option images, course scoping, the Images list, alt text, delete, replace, images
following a moved game, concurrency, sockets, export/import and the report.
"""

from __future__ import annotations

import asyncio

import httpx

from . import t4_helpers
from .t4_helpers import T4World, assert_error, png, upload_ok
from .test_map_pin import (
    assert_validation_error,
    create_q,
    export_bundle,
    finish,
    import_bundle,
    map_pin_question,
    next_question,
    open_game,
    results,
    submit,
    update_q,
)

t4 = t4_helpers.t4  # fixture


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def mc(options: list[str], image_ids: list[str | None] | None = None, **extra) -> dict:
    config: dict = {"options": options}
    if image_ids is not None:
        config["optionImageIds"] = image_ids
    config.update(extra.pop("config", {}))
    body = {
        "type": "multiple_choice",
        "grading_type": "ACCURACY",
        "prompt": "Which one?",
        "config": config,
        "answer_data": {"answer_points": [1] + [0] * (len(options) - 1)},
        "points_value": 1,
    }
    body.update(extra)
    return body


def ms(options: list[str], image_ids: list[str | None]) -> dict:
    return {
        "type": "multi_select",
        "grading_type": "ACCURACY",
        "prompt": "Pick all",
        "config": {"options": options, "optionImageIds": image_ids},
        "answer_data": {"answer_points": [1] * len(options)},
        "points_value": len(options),
    }


def with_prompt_image(body: dict, image_id: str) -> dict:
    return {**body, "config": {**body.get("config", {}), "promptImageId": image_id}}


TYPE_BODIES = {
    "multiple_choice": mc(["a", "b"]),
    "multi_select": {
        "type": "multi_select",
        "grading_type": "COMPLETENESS",
        "prompt": "p",
        "config": {"options": ["a", "b"]},
    },
    "true_false": {
        "type": "true_false",
        "grading_type": "ACCURACY",
        "prompt": "p",
        "answer_data": {"answer_points": {"true": 1, "false": 0}},
    },
    "fill_in_the_blank": {
        "type": "fill_in_the_blank",
        "grading_type": "ACCURACY",
        "prompt": "p",
        "answer_data": {"acceptedAnswers": ["x"], "answerPoints": [1]},
    },
}


def created(r: httpx.Response) -> dict:
    assert r.status_code == 201, r.text
    return r.json()


def admin_list(t4: T4World, **params) -> list[dict]:
    r = t4.request("GET", "/admin/images", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def host_list(t4: T4World, course: int, token: str) -> list[dict]:
    r = t4.request("GET", f"/host/courses/{course}/images", token)
    assert r.status_code == 200, r.text
    return r.json()


def by_id(items: list[dict], image_id: str) -> dict:
    return next(i for i in items if i["id"] == image_id)


def replace(
    t4: T4World,
    image_id: str,
    data: bytes,
    token: str | None = None,
    *,
    host: bool = False,
    alt_text: str | None = None,
) -> httpx.Response:
    prefix = "/host" if host else "/admin"
    form = {"alt_text": alt_text} if alt_text is not None else None
    r = t4.request(
        "POST",
        f"{prefix}/images/{image_id}/replace",
        token,
        files={"file": ("new.png", data, "image/png")},
        data=form,
    )
    if r.status_code == 201:
        t4.track_image(r.json()["id"])
    return r


def get_question(t4: T4World, game: int, qid: int) -> dict:
    r = t4.request("GET", f"/admin/games/{game}/questions")
    assert r.status_code == 200, r.text
    return next(q for q in r.json() if q["id"] == qid)


def move(t4: T4World, game: int, course: int, confirm: bool) -> dict:
    r = t4.request(
        "POST",
        f"/admin/games/{game}/move",
        json={"course_id": course, "confirm": confirm},
    )
    assert r.status_code == 200, r.text
    return r.json()


def host_world(t4: T4World) -> tuple[int, t4_helpers.T4User, int]:
    course = t4.course()
    host = t4.user()
    t4.grant_course(host, course)
    return course, host, t4.game(course)


# ---------------------------------------------------------------------------
# Validation (§4.2)
# ---------------------------------------------------------------------------


def test_prompt_image_on_every_type(t4: T4World):
    img = upload_ok(t4, png())
    game = t4.game(t4.course())
    for type_, body in TYPE_BODIES.items():
        q = created(create_q(t4, game, with_prompt_image(body, img["id"])))
        assert q["config"]["promptImageId"] == img["id"], type_
        assert q["image_alt"] == {img["id"]: ""}
    q = created(
        create_q(t4, game, map_pin_question(img["id"], promptImageId=img["id"]))
    )
    assert q["config"]["promptImageId"] == img["id"]


def test_option_image_rules(t4: T4World):
    a, b = upload_ok(t4, png()), upload_ok(t4, png())
    game = t4.game(t4.course())

    q = created(create_q(t4, game, mc(["", "text", ""], [a["id"], None, a["id"]])))
    assert q["config"]["optionImageIds"] == [a["id"], None, a["id"]]
    created(create_q(t4, game, ms(["", ""], [a["id"], b["id"]])))
    # All-null list is treated as absent: blank text stays allowed.
    created(create_q(t4, game, mc(["", "b"], [None, None])))

    for body in (
        mc(["a", "b"], [a["id"]]),  # length mismatch
        mc(["a", "b"], [a["id"], None]),  # both
        mc(["", "b"], [None, b["id"]]),  # neither for option 1
        {**TYPE_BODIES["true_false"], "config": {"optionImageIds": [a["id"]]}},
    ):
        assert_validation_error(create_q(t4, game, body))

    r = create_q(
        t4, game, mc(["", "b"], ["00000000-0000-4000-8000-000000000000", None])
    )
    assert_error(r, 422, "IMAGE_NOT_FOUND")

    # Same rules on PUT (merged validation).
    r = update_q(t4, game, q["id"], {"config": {"options": ["x", "", ""]}})
    assert r.status_code == 200, r.text  # dropping optionImageIds → old rules
    r = update_q(
        t4,
        game,
        q["id"],
        {"config": {"options": ["x", "y"], "optionImageIds": [a["id"], None]}},
    )
    assert_validation_error(r)


# ---------------------------------------------------------------------------
# Course scoping (§4.4)
# ---------------------------------------------------------------------------


def test_course_scoping(t4: T4World):
    course, host, game = host_world(t4)
    other = t4.course()
    mine = upload_ok(t4, png(), token=host.token, host_course=course)
    foreign = upload_ok(t4, png(), course_id=other)
    unassigned = upload_ok(t4, png())

    created(
        create_q(
            t4,
            game,
            with_prompt_image(mc(["a", "b"]), mine["id"]),
            host.token,
            host=True,
        )
    )
    for img in (foreign, unassigned):
        r = create_q(
            t4,
            game,
            with_prompt_image(mc(["a", "b"]), img["id"]),
            host.token,
            host=True,
        )
        assert_error(r, 422, "IMAGE_NOT_IN_COURSE")
    # Admins may use any image.
    q = created(create_q(t4, game, with_prompt_image(mc(["a", "b"]), foreign["id"])))

    # An image the question already has isn't re-checked: a prompt-only host edit
    # of a question that keeps another course's image still saves.
    r = update_q(t4, game, q["id"], {"prompt": "Edited"}, host.token, host=True)
    assert r.status_code == 200, r.text
    # …but adding a new foreign image is refused.
    r = update_q(
        t4,
        game,
        q["id"],
        {
            "config": {
                "options": ["", "b"],
                "optionImageIds": [unassigned["id"], None],
                "promptImageId": foreign["id"],
            }
        },
        host.token,
        host=True,
    )
    assert_error(r, 422, "IMAGE_NOT_IN_COURSE")


# ---------------------------------------------------------------------------
# List and usage (§4.5, §4.6)
# ---------------------------------------------------------------------------


def test_lists_usage_and_filters(t4: T4World):
    course, host, game = host_world(t4)
    other = t4.course()
    img = upload_ok(t4, png(), token=host.token, host_course=course, alt_text=" Dog ")
    foreign = upload_ok(t4, png(), course_id=other)
    loose = upload_ok(t4, png())
    assert img["alt_text"] == "Dog" and img["course_id"] == course

    created(create_q(t4, game, mc(["a", "b"])))  # Q1, no images
    q2 = created(
        create_q(
            t4, game, with_prompt_image(mc(["", "b"], [img["id"], None]), img["id"])
        )
    )
    # A restricted game the host has no grant on, using the same image.
    hidden_game = t4.game(course, restricted=True)
    created(create_q(t4, hidden_game, with_prompt_image(mc(["a", "b"]), img["id"])))

    items = host_list(t4, course, host.token)
    assert {i["id"] for i in items} == {img["id"]}
    item = items[0]
    assert sorted(u["role"] for u in item["usage"]) == ["option", "prompt"]
    assert {u["question_id"] for u in item["usage"]} == {q2["id"]}
    assert item["usage"][0]["question_number"] == 2
    assert item["usage"][0]["course_id"] == course
    assert item["hidden_usage_count"] == 1

    admin_item = by_id(admin_list(t4, course_id=course), img["id"])
    assert len(admin_item["usage"]) == 3 and admin_item["hidden_usage_count"] == 0
    assert {i["id"] for i in admin_list(t4, course_id=other)} == {foreign["id"]}
    assert loose["id"] in {i["id"] for i in admin_list(t4, unassigned="true")}
    assert foreign["id"] not in {i["id"] for i in admin_list(t4, unassigned="true")}
    r = t4.request(
        "GET", "/admin/images", params={"course_id": other, "unassigned": "true"}
    )
    assert_error(r, 422, "VALIDATION_ERROR")


def test_list_access(t4: T4World):
    course, host, _ = host_world(t4)
    stranger = t4.user("t8_stranger")
    assert_error(
        t4.request("GET", f"/host/courses/{course}/images", stranger.token),
        403,
        "FORBIDDEN",
    )
    assert t4.request("GET", "/admin/images", host.token).status_code == 403
    r = t4.create_room(t4.game(course), course)
    guest = t4.guest_token(r.json()["room_code"])
    assert t4.request("GET", f"/host/courses/{course}/images", guest).status_code == 403


def test_question_number_is_position(t4: T4World):
    img = upload_ok(t4, png())
    game = t4.game(t4.course())
    q1 = created(create_q(t4, game, mc(["a", "b"])))
    created(create_q(t4, game, mc(["a", "b"])))
    q3 = created(create_q(t4, game, with_prompt_image(mc(["a", "b"]), img["id"])))
    assert (
        t4.request("DELETE", f"/admin/games/{game}/questions/{q1['id']}").status_code
        == 204
    )
    use = by_id(admin_list(t4, unassigned="true"), img["id"])["usage"][0]
    assert use["question_id"] == q3["id"] and use["question_number"] == 2


# ---------------------------------------------------------------------------
# Alt text (§4.1, §4.5, §4.8)
# ---------------------------------------------------------------------------


async def test_alt_text(t4: T4World):
    course = t4.course()
    img = upload_ok(t4, png(), course_id=course, alt_text="A red square")
    assert img["alt_text"] == "A red square"
    r = t4.request("PATCH", f"/admin/images/{img['id']}", json={"alt_text": "  Blue  "})
    assert r.status_code == 200 and r.json()["alt_text"] == "Blue", r.text
    r = t4.request("PATCH", f"/admin/images/{img['id']}", json={"alt_text": "x" * 251})
    assert_validation_error(r)
    r = t4_helpers.upload(t4, png(), alt_text="x" * 251)
    assert_error(r, 422, "VALIDATION_ERROR")

    game = t4.game(course)
    created(create_q(t4, game, mc(["", "b"], [img["id"], None])))
    live = await open_game(t4, course, game, 1)
    try:
        await live.host.emit("host_advance", {})
        payload = await live.players[0].wait_for("new_question")
        assert payload["imageAlt"] == {img["id"]: "Blue"}
        assert payload["config"]["optionImageIds"] == [img["id"], None]
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Delete (§4.6)
# ---------------------------------------------------------------------------


def test_delete(t4: T4World):
    course, host, game = host_world(t4)
    unused = upload_ok(t4, png(), course_id=course)
    assert t4.request("DELETE", f"/admin/images/{unused['id']}").status_code == 204
    assert t4.request("GET", f"/images/{unused['id']}").status_code == 404

    m, p, o = (upload_ok(t4, png(), course_id=course) for _ in range(3))
    created(create_q(t4, game, map_pin_question(m["id"])))
    created(create_q(t4, game, with_prompt_image(mc(["a", "b"]), p["id"])))
    created(create_q(t4, game, mc(["", "b"], [o["id"], None])))
    for img, role in ((m, "map"), (p, "prompt"), (o, "option")):
        r = t4.request("DELETE", f"/admin/images/{img['id']}")
        assert_error(r, 409, "IMAGE_IN_USE")
        assert [u["role"] for u in r.json()["usage"]] == [role]
        assert r.json()["hidden_usage_count"] == 0

    # Host's 409 hides uses in a restricted game they have no grant on.
    hidden_game = t4.game(course, restricted=True)
    created(create_q(t4, hidden_game, with_prompt_image(mc(["a", "b"]), p["id"])))
    r = t4.request("DELETE", f"/host/images/{p['id']}", host.token)
    assert_error(r, 409, "IMAGE_IN_USE")
    assert len(r.json()["usage"]) == 1 and r.json()["hidden_usage_count"] == 1

    # Host on another course's image → 403; courseless image → host 403, admin OK.
    other_img = upload_ok(t4, png(), course_id=t4.course())
    assert_error(
        t4.request("DELETE", f"/host/images/{other_img['id']}", host.token),
        403,
        "FORBIDDEN",
    )
    loose = upload_ok(t4, png())
    assert_error(
        t4.request("DELETE", f"/host/images/{loose['id']}", host.token),
        403,
        "FORBIDDEN",
    )
    assert t4.request("DELETE", f"/admin/images/{loose['id']}").status_code == 204
    assert_error(
        t4.request("DELETE", f"/host/images/{loose['id']}", host.token),
        404,
        "NOT_FOUND",
    )


# ---------------------------------------------------------------------------
# Replace (§4.7)
# ---------------------------------------------------------------------------


def test_replace_repoints_every_use(t4: T4World):
    course = t4.course()
    old = upload_ok(t4, png(), course_id=course, alt_text="old")
    g1, g2 = t4.game(course), t4.game(course)
    q1 = created(create_q(t4, g1, mc(["", "", "t"], [old["id"], old["id"], None])))
    q2 = created(create_q(t4, g2, with_prompt_image(mc(["a", "b"]), old["id"])))

    new = created(replace(t4, old["id"], png((60, 30))))
    assert new["id"] != old["id"] and new["course_id"] == course
    assert new["alt_text"] == "old"  # kept when the form has none
    assert get_question(t4, g1, q1["id"])["config"]["optionImageIds"] == [
        new["id"],
        new["id"],
        None,
    ]
    assert get_question(t4, g2, q2["id"])["config"]["promptImageId"] == new["id"]
    assert t4.request("DELETE", f"/admin/images/{old['id']}").status_code == 204


def test_replace_map_aspect(t4: T4World):
    course = t4.course()
    old = upload_ok(t4, png((80, 40)), course_id=course)
    game = t4.game(course)
    q = created(create_q(t4, game, map_pin_question(old["id"])))

    assert_error(replace(t4, old["id"], png((40, 40))), 422, "IMAGE_ASPECT_MISMATCH")
    assert get_question(t4, game, q["id"])["config"]["imageId"] == old["id"]

    new = created(replace(t4, old["id"], png((160, 80)), alt_text="Bigger"))
    config = get_question(t4, game, q["id"])["config"]
    assert config == {"imageId": new["id"], "imageWidth": 160, "imageHeight": 80}
    assert new["alt_text"] == "Bigger"


async def test_replace_refused_while_live(t4: T4World):
    course = t4.course()
    old = upload_ok(t4, png(), course_id=course)
    game = t4.game(course)
    q = created(create_q(t4, game, mc(["", "b"], [old["id"], None])))
    live = await open_game(t4, course, game, 1)
    try:
        await next_question(live)
        assert_error(replace(t4, old["id"], png()), 409, "GAME_LIVE")
        assert (
            get_question(t4, game, q["id"])["config"]["optionImageIds"][0] == old["id"]
        )
    finally:
        await live.close()


def test_replace_host_rules_and_body_limit(t4: T4World):
    course, host, game = host_world(t4)
    img = upload_ok(t4, png(), token=host.token, host_course=course)
    created(create_q(t4, game, with_prompt_image(mc(["a", "b"]), img["id"])))
    created(replace(t4, img["id"], png(), host.token, host=True))  # own game: OK

    img2 = upload_ok(t4, png(), token=host.token, host_course=course)
    hidden_game = t4.game(course, restricted=True)
    created(create_q(t4, hidden_game, with_prompt_image(mc(["a", "b"]), img2["id"])))
    assert_error(
        replace(t4, img2["id"], png(), host.token, host=True), 403, "FORBIDDEN"
    )

    big = b"\0" * (3 * 1024 * 1024)
    r = t4.request(
        "POST",
        f"/admin/images/{img2['id']}/replace",
        files={"file": ("x.png", big, "image/png")},
    )
    assert r.status_code == 413, r.text


# ---------------------------------------------------------------------------
# Images follow a moved game (§4.7a)
# ---------------------------------------------------------------------------


def test_move_retags_exclusive_and_copies_shared(t4: T4World):
    a_course, b_course = t4.course(), t4.course()
    exclusive = upload_ok(t4, png(), course_id=a_course)
    shared = upload_ok(t4, png((40, 80)), course_id=a_course, alt_text="shared")
    moving, staying = t4.game(a_course), t4.game(a_course)
    qm = created(
        create_q(
            t4,
            moving,
            with_prompt_image(mc(["", "b"], [shared["id"], None]), exclusive["id"]),
        )
    )
    created(create_q(t4, staying, mc(["", "b"], [shared["id"], None])))

    preview = move(t4, moving, b_course, confirm=False)
    assert (preview["images_moved"], preview["images_copied"]) == (1, 1)
    assert by_id(admin_list(t4, course_id=a_course), exclusive["id"])  # nothing written

    applied = move(t4, moving, b_course, confirm=True)
    assert (applied["images_moved"], applied["images_copied"]) == (1, 1)

    config = get_question(t4, moving, qm["id"])["config"]
    assert config["promptImageId"] == exclusive["id"]  # same ID, re-tagged
    copy_id = config["optionImageIds"][0]
    assert copy_id != shared["id"]
    t4.track_image(copy_id)
    b_images = {i["id"]: i for i in admin_list(t4, course_id=b_course)}
    assert set(b_images) == {exclusive["id"], copy_id}
    copy = b_images[copy_id]
    assert copy["sha256"] == shared["sha256"] and copy["alt_text"] == "shared"
    assert (copy["width"], copy["height"]) == (40, 80)
    # The game that stayed keeps the original, still in course A.
    orig = by_id(admin_list(t4, course_id=a_course), shared["id"])
    assert [u["game_id"] for u in orig["usage"]] == [staying]

    # A host of the new course now sees and can replace both.
    host = t4.user()
    t4.grant_course(host, b_course)
    assert {i["id"] for i in host_list(t4, b_course, host.token)} == set(b_images)
    created(replace(t4, copy_id, png((40, 80)), host.token, host=True))


def test_first_room_attach_tags_courseless_images(t4: T4World):
    course = t4.course()
    loose = upload_ok(t4, png())
    game = t4.game(None)
    created(create_q(t4, game, with_prompt_image(mc(["a", "b"]), loose["id"])))
    r = t4.create_room(game, course)
    assert r.status_code == 201, r.text
    assert by_id(admin_list(t4, course_id=course), loose["id"])["course_id"] == course


# ---------------------------------------------------------------------------
# Concurrency (§4.0, §4.4, §4.6)
# ---------------------------------------------------------------------------


async def test_concurrent_save_and_delete(t4: T4World):
    course = t4.course()
    game = t4.game(course)
    existing = created(create_q(t4, game, mc(["a", "b"])))

    async def pair(edit: bool) -> None:
        img = upload_ok(t4, png(), course_id=course)
        if edit:
            # Edit a question that already uses the image.
            q = created(
                create_q(t4, game, with_prompt_image(mc(["a", "b"]), img["id"]))
            )
            save = lambda: update_q(t4, game, q["id"], {"prompt": "Edited"})
        else:
            body = with_prompt_image(mc(["a", "b"]), img["id"])
            save = lambda: create_q(t4, game, body)
        delete = lambda: t4.request("DELETE", f"/admin/images/{img['id']}")
        s, d = await asyncio.gather(asyncio.to_thread(save), asyncio.to_thread(delete))
        assert s.status_code != 500 and d.status_code != 500, (s.text, d.text)
        image_alive = t4.request("GET", f"/images/{img['id']}").status_code == 200
        saved = s.status_code in (200, 201)
        if saved:
            assert image_alive, "a saved question points at a deleted image"
            assert d.status_code in (409,), d.text
        else:
            assert s.status_code in (409, 422), s.text
            if s.status_code == 422:
                assert s.json()["error"] == "IMAGE_NOT_FOUND"
        if d.status_code == 204:
            assert not image_alive
        if d.status_code == 409 and not saved:
            assert d.json()["error"] in ("IMAGE_IN_USE", "CONFLICT")

    for edit in (False, True):
        await asyncio.gather(*(pair(edit) for _ in range(10)))
    assert get_question(t4, game, existing["id"])


# ---------------------------------------------------------------------------
# Sockets (§4.8)
# ---------------------------------------------------------------------------


async def test_socket_preload_and_scoring(t4: T4World):
    course = t4.course()
    prompt_only = upload_ok(t4, png())
    opt = upload_ok(t4, png())
    game = t4.game(course)
    created(
        create_q(
            t4,
            game,
            with_prompt_image(mc(["", "b"], [opt["id"], None]), prompt_only["id"]),
        )
    )
    live = await open_game(t4, course, game, 2)
    try:
        sync = await live.players[0].wait_for("sync_state")
        assert sync["imageIds"] == [opt["id"]]
        await live.host.emit("host_advance", {})
        assert await live.players[0].wait_for("game_images") == {
            "imageIds": [opt["id"]]
        }
        host_sets = [
            (await live.host.wait_for("game_images"))["imageIds"] for _ in range(2)
        ]
        assert [opt["id"]] in host_sets and [prompt_only["id"], opt["id"]] in host_sets
        payload = await live.host.wait_for("new_question")
        assert payload["imageAlt"] == {prompt_only["id"]: "", opt["id"]: ""}
        qid = payload["questionId"]
        for p in live.players:
            await p.wait_for("new_question")
        assert (await submit(live.players[0], qid, {"selectedIndex": 0}))[
            0
        ] == "answer_received"
        assert (await submit(live.players[1], qid, {"selectedIndex": 1}))[
            0
        ] == "answer_received"
        res = await results(live)
        assert res["answerReveal"]["correctIndices"] == [0]
        over = await finish(live)
        summary = over["questionSummary"][0]
        assert summary["imageAlt"] == {prompt_only["id"]: "", opt["id"]: ""}
    finally:
        await live.close()


# ---------------------------------------------------------------------------
# Export / import (§4.9)
# ---------------------------------------------------------------------------


def test_export_import_round_trip(t4: T4World):
    course = t4.course()
    p = upload_ok(t4, png(), course_id=course, alt_text="Prompt pic")
    o = upload_ok(t4, png((40, 80)), course_id=course, alt_text="Option pic")
    game = t4.game(course)
    created(
        create_q(t4, game, with_prompt_image(mc(["", "b"], [o["id"], None]), p["id"]))
    )

    bundle = export_bundle(t4, game)
    assert bundle["version"] == 2
    assert {i["id"]: i["alt_text"] for i in bundle["images"]} == {
        p["id"]: "Prompt pic",
        o["id"]: "Option pic",
    }

    target = t4.course()
    new_game = created(import_bundle(t4, bundle, target))["game_id"]
    q = next(iter(t4.request("GET", f"/admin/games/{new_game}/questions").json()))
    new_p, new_o = q["config"]["promptImageId"], q["config"]["optionImageIds"][0]
    assert {new_p, new_o}.isdisjoint({p["id"], o["id"]})
    imported = {i["id"]: i for i in admin_list(t4, course_id=target)}
    for i in imported:
        t4.track_image(i)
    assert imported[new_p]["alt_text"] == "Prompt pic"
    assert imported[new_o]["alt_text"] == "Option pic"

    # v2 without alt_text still imports.
    for image in bundle["images"]:
        image.pop("alt_text")
    created(import_bundle(t4, bundle, target))
    for i in admin_list(t4, course_id=target):
        t4.track_image(i["id"])


def test_import_rejects_missing_images(t4: T4World):
    course = t4.course()
    o = upload_ok(t4, png(), course_id=course)
    game = t4.game(course)
    created(create_q(t4, game, mc(["", "b"], [o["id"], None])))
    bundle = export_bundle(t4, game)

    missing = {**bundle, "images": []}
    r = import_bundle(t4, missing, course)
    assert r.status_code == 422 and "not in bundle" in r.text, r.text

    v1 = {**bundle, "version": 1}
    v1.pop("images")
    r = import_bundle(t4, v1, course)
    assert r.status_code == 422 and "not in bundle" in r.text, r.text

    bad_alt = {**bundle, "images": [{**bundle["images"][0], "alt_text": 5}]}
    r = import_bundle(t4, bad_alt, course)
    assert r.status_code == 422 and "alt_text" in r.text, r.text


# ---------------------------------------------------------------------------
# Report (§4.12)
# ---------------------------------------------------------------------------


async def test_report_embeds_each_image_once(t4: T4World):
    course = t4.course()
    opt = upload_ok(t4, png(), course_id=course, alt_text="Option pic")
    prompt = upload_ok(t4, png(), course_id=course)
    game = t4.game(course)
    created(
        create_q(
            t4, game, with_prompt_image(mc(["", "b"], [opt["id"], None]), prompt["id"])
        )
    )
    created(create_q(t4, game, mc(["", "b"], [opt["id"], None])))
    live = await open_game(t4, course, game, 1)
    try:
        for _ in range(2):
            qid = await next_question(live)
            await submit(live.players[0], qid, {"selectedIndex": 0})
            await results(live)
        await finish(live)
    finally:
        await live.close()

    r = t4.request("GET", f"/admin/sessions/{live.session_id}/report")
    assert r.status_code == 200, r.text
    html = r.text
    assert html.count(f'id="img-{opt["id"]}"') == 1
    assert html.count(f'id="img-{prompt["id"]}"') == 1
    assert html.count(f'href="#img-{opt["id"]}"') == 2
    assert "Option pic" in html

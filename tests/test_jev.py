import json

import pytest
import requests

from jev_browser import camofox, jev

from helpers import make_state


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)


def answer(choice, ids, confidence=0.8):
    probabilities = {i: 0.0 for i in ids}
    probabilities[choice] = 1.0
    return {"choice": choice, "probabilities": probabilities, "confidence": confidence}


class Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def test_api_key_prefers_the_jev_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "general")
    monkeypatch.setenv("JEV_OPENROUTER_KEY", "jev")
    assert jev.api_key() == "jev"
    monkeypatch.delenv("JEV_OPENROUTER_KEY")
    assert jev.api_key() == "general"


def test_post_json_without_a_key_refuses(monkeypatch):
    monkeypatch.delenv("JEV_OPENROUTER_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(jev.ModelError, match="No OpenRouter key"):
        jev.post_json("https://x.test", {})


def test_post_json_retries_rate_limits_then_returns(monkeypatch, key):
    replies = iter([Response(429), Response(200, {"ok": 1})])
    sent = []

    def post(url, json, headers, timeout):
        sent.append(headers["Authorization"])
        return next(replies)

    monkeypatch.setattr(jev._HTTP, "post", post)
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    assert jev.post_json("https://x.test", {}) == {"ok": 1}
    assert sent == ["Bearer test-key"] * 2


def test_post_json_gives_up_after_three_rate_limits(monkeypatch, key):
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: Response(503))
    monkeypatch.setattr(jev.time, "sleep", lambda s: None)
    with pytest.raises(jev.ModelError, match="HTTP 503"):
        jev.post_json("https://x.test", {})


def test_post_json_maps_a_non_json_reply(monkeypatch, key):
    class Bad(Response):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: Bad(200))
    with pytest.raises(jev.ModelError, match="non-JSON"):
        jev.post_json("https://x.test", {})


def test_post_json_maps_connection_errors(monkeypatch, key):
    def post(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(jev._HTTP, "post", post)
    with pytest.raises(jev.ModelError, match="connection failed"):
        jev.post_json("https://x.test", {})


def test_choose_offers_need_guidance_and_resolves_the_target(monkeypatch, key):
    sent = {}

    def post_json(url, body):
        sent.update(url=url, body=body)
        ops = list(body["questions"]["operation"]["criteria"])
        targets = list(body["questions"]["click_target"]["criteria"])
        return {"answers": {"operation": answer("CLICK", ops, 0.9), "click_target": answer("2", targets, 0.6)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    d = jev.choose(make_state(), "press go", [])

    assert d["choice"] == "e2" and d["operation"] == "CLICK"
    assert (d["confidence"], d["target_confidence"]) == (0.9, 0.6)
    assert sent["url"] == jev.DECISIONS_URL
    assert sent["body"]["model"] == "~typesafe/jev-latest"
    assert {"DONE", "BLOCKED", "NEED_GUIDANCE", "WAIT"} <= set(sent["body"]["questions"]["operation"]["criteria"])


def test_choose_returns_stop_choices_directly(monkeypatch, key):
    def post_json(url, body):
        ops = list(body["questions"]["operation"]["criteria"])
        return {"answers": {"operation": answer("NEED_GUIDANCE", ops, 0.7)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    assert jev.choose(make_state(), "goal", [])["choice"] == "NEED_GUIDANCE"


def test_choose_maps_controls_to_their_action_ids(monkeypatch, key):
    def post_json(url, body):
        ops = list(body["questions"]["operation"]["criteria"])
        return {"answers": {"operation": answer("WAIT", ops)}}

    monkeypatch.setattr(jev, "post_json", post_json)
    assert jev.choose(make_state(), "goal", [])["choice"] == "wait"


@pytest.mark.parametrize("reply", [{}, {"answers": None}, {"answers": {"operation": {"choice": "NOPE"}}}])
def test_choose_rejects_malformed_answers(monkeypatch, key, reply):
    monkeypatch.setattr(jev, "post_json", lambda url, body: reply)
    with pytest.raises(jev.ModelError):
        jev.choose(make_state(), "goal", [])


def test_select_options_get_their_own_target_indices():
    actions = [
        {"id": "e1", "kind": "select", "node": 5, "label": "Class → Economy", "value": "eco", "current_value": ""},
        {"id": "e2", "kind": "select", "node": 5, "label": "Class → Business", "value": "bus", "current_value": ""},
    ]
    elements, targets, _ = jev.action_space(actions)
    assert list(targets["SELECT"]) == ["1:1", "1:2"]
    assert [o["value"] for o in elements[0]["options"]] == ["eco", "bus"]


def chat(content):
    return {"choices": [{"message": {"content": content}}]}


def test_field_text_returns_the_value(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": "London"})))
    assert jev.field_text({"goal": "g"}) == "London"


def test_field_text_null_means_the_goal_lacks_the_value(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": None})))
    assert jev.field_text({"goal": "g"}) is None


def test_field_text_retries_malformed_output_once(monkeypatch, key):
    replies = iter([chat("not json"), chat(json.dumps({"text": "ok"}))])
    monkeypatch.setattr(jev, "post_json", lambda url, body: next(replies))
    assert jev.field_text({"goal": "g"}) == "ok"


def test_field_text_raises_after_two_malformed_answers(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", lambda url, body: chat(json.dumps({"text": ""})))
    with pytest.raises(jev.ModelError, match="no valid field value"):
        jev.field_text({"goal": "g"})


def test_field_context_caps_page_text():
    ctx = jev.field_context("g", {"label": "L"}, make_state(text="x" * 9000), [])
    assert len(ctx["page"]["text"]) == 6000


def goal_reply(operation, probability, *, operation_probabilities=None, target="2"):
    """A reply whose goal check answers `probability` alongside the usual heads."""
    def post_json(url, body):
        post_json.bodies.append(body)
        ops = list(body["questions"]["operation"]["criteria"])
        op = answer(operation, ops, 0.9)
        if operation_probabilities:
            op["probabilities"] = {i: operation_probabilities.get(i, 0.0) for i in ops}
        targets = list(body["questions"]["click_target"]["criteria"])
        answers = {"operation": op, "click_target": answer(target, targets, 0.9)}
        if probability is not None:
            answers["goal_satisfied"] = {"type": "noul", "noul": probability}
        return {"answers": answers}
    post_json.bodies = []
    return post_json


def test_every_decision_asks_whether_the_goal_is_met_in_the_same_request(monkeypatch, key):
    post = goal_reply("CLICK", 0.5)
    monkeypatch.setattr(jev, "post_json", post)
    jev.choose(make_state(), "open the first result", [])
    question = post.bodies[0]["questions"]["goal_satisfied"]
    assert len(post.bodies) == 1 and question["type"] == "noul"
    assert question["instructions"]["goal"] == "open the first result"
    assert "submit" in question["instructions"]["question"]  # an offered action is not a completed one


def test_choose_reports_the_goal_check_and_the_heads_support_for_done(monkeypatch, key):
    probabilities = {"CLICK": 0.7, "DONE": 0.3}
    monkeypatch.setattr(jev, "post_json", goal_reply("CLICK", 0.96, operation_probabilities=probabilities))
    d = jev.choose(make_state(), "open the comments", [])
    assert d["operation"] == "CLICK" and d["completion_probability"] == 0.96 and d["done_probability"] == 0.3


def check(operation="CLICK", confidence=0.9, target=0.9, done=0.0, completion=0.96):
    return {"operation": operation, "confidence": confidence, "target_confidence": target,
            "done_probability": done, "completion_probability": completion}


@pytest.mark.parametrize("decision", [
    check(done=0.3),                      # the operation head itself sees completion as possible
    check(confidence=0.2),                # its chosen operation is below the floor
    check(target=0.1),                    # its chosen target is below the target floor
    check(operation="WAIT", target=None, done=0.2),
])
def test_a_confident_goal_check_may_finish_where_the_head_leaves_room(decision):
    assert jev.goal_met(decision, 0.35, 0.2)


@pytest.mark.parametrize("decision", [
    check(operation="NEED_GUIDANCE", target=None, done=0.4),
    check(operation="BLOCKED", target=None, done=0.4),
    check(done=0.1),                      # a confident action with negligible support for DONE
    check(done=0.4, completion=0.89),
    check(done=0.4, completion=None),
])
def test_a_goal_check_never_overrides_a_stop_a_confident_action_or_an_unsure_check(decision):
    assert not jev.goal_met(decision, 0.35, 0.2)


@pytest.mark.parametrize("probability", [None, 0.5, 0.89, float("nan"), "0.99", 1.5])
def test_an_action_the_goal_still_requires_is_taken(monkeypatch, key, probability):
    monkeypatch.setattr(jev, "post_json", goal_reply("CLICK", probability))
    d = jev.choose(make_state(), "submit the form", [])
    assert d["choice"] == "e2" and d["operation"] == "CLICK" and d.get("goal_check") is None
    assert d["completion_probability"] == (probability if probability in (0.5, 0.89) else None)
    assert not jev.goal_met(d, 0.35, 0.2)


def test_done_contradicted_by_the_goal_check_continues_with_the_next_best_operation(monkeypatch, key):
    probabilities = {"DONE": 0.5, "CLICK": 0.45, "WAIT": 0.05}
    monkeypatch.setattr(jev, "post_json", goal_reply("DONE", 0.1, operation_probabilities=probabilities))
    d = jev.choose(make_state(), "submit the form", [])
    # Scored on its own probability: renormalizing would inflate a weak runner-up.
    assert d["choice"] == "e2" and d["operation"] == "CLICK" and d["goal_check"] == "unmet"
    assert d["confidence"] == 0.45 and d["target_confidence"] == 0.9


def test_a_weak_runner_up_after_overruling_done_is_not_inflated(monkeypatch, key):
    probabilities = {"DONE": 0.9, "CLICK": 0.05, "WAIT": 0.05}
    monkeypatch.setattr(jev, "post_json", goal_reply("DONE", 0.1, operation_probabilities=probabilities))
    d = jev.choose(make_state(), "submit the form", [])
    assert d["goal_check"] == "unmet" and d["confidence"] == 0.05  # renormalized it scored 0.417


def test_done_is_kept_when_the_goal_check_is_unsure(monkeypatch, key):
    monkeypatch.setattr(jev, "post_json", goal_reply("DONE", 0.5))
    assert jev.choose(make_state(), "goal", [])["choice"] == "DONE"


def guard(label, href=None, role="link"):
    """A snapshot.js cache.guard tuple; index 14 is the element's href attribute."""
    return [0, role, label, None, None, None, None, None, None, False, None, None, None, None, href, "scope"]


def duplicates(*controls):
    """Click targets from (label, href, role) tuples, with matching executor guards."""
    actions = [{"id": f"e{n}", "kind": "click", "node": n, "label": label, "role": role, "value": ""}
               for n, (label, href, role) in enumerate(controls, 1)]
    state = make_state(actions=actions)
    state["guards"] = {str(n): guard(label, href, role) for n, (label, href, role) in enumerate(controls, 1)}
    return state


def split_reply(probabilities, choice):
    def post_json(url, body):
        ops = list(body["questions"]["operation"]["criteria"])
        targets = list(body["questions"]["click_target"]["criteria"])
        target = {"choice": choice, "probabilities": {i: probabilities.get(i, 0.0) for i in targets},
                  "confidence": choice_confidence_of(probabilities, len(targets))}
        return {"answers": {"operation": answer("CLICK", ops, 0.9), "click_target": target}}
    return post_json


def choice_confidence_of(probabilities, n):
    return (max(probabilities.values()) - 1 / n) / (1 - 1 / n)


def test_equivalent_links_pool_their_probability_and_act_on_the_first(monkeypatch, key):
    state = duplicates(("Downloads", "/downloads/", "link"), ("About", "/about/", "link"),
                       (" downloads ", "/downloads/", "link"))
    monkeypatch.setattr(jev, "post_json", split_reply({"1": 0.44, "2": 0.12, "3": 0.44}, "3"))
    d = jev.choose(state, "open the downloads page", [])
    assert d["choice"] == "e1"  # the first observed member; the executor still validates it
    assert d["target_confidence"] == pytest.approx(jev.choice_confidence([0.88, 0.12]))


@pytest.mark.parametrize("href", ["#", "#cart", "javascript:void(0)", " JavaScript:add(2)", ""])
def test_script_handled_links_are_never_pooled(monkeypatch, key, href):
    # "Add to cart" on every row, all href="#": pooling would click the wrong row.
    state = duplicates(("Add to cart", href, "link"), ("Add to cart", href, "link"), ("Add to cart", href, "link"))
    monkeypatch.setattr(jev, "post_json", split_reply({"1": 0.02, "2": 0.95, "3": 0.03}, "2"))
    d = jev.choose(state, "add the second item to the cart", [])
    assert d["choice"] == "e2" and d["target_confidence"] == pytest.approx((0.95 - 1 / 3) / (2 / 3))


def test_a_pooled_class_acts_on_the_member_jev_preferred(monkeypatch, key):
    state = duplicates(("Comments", "item?id=1", "link"), ("Comments", "item?id=1", "link"), ("Hide", "hide", "link"))
    monkeypatch.setattr(jev, "post_json", split_reply({"1": 0.1, "2": 0.85, "3": 0.05}, "2"))
    assert jev.choose(state, "open the comments", [])["choice"] == "e2"


@pytest.mark.parametrize("controls", [
    [("Delete", None, "button"), ("Delete", None, "button")],  # no shared destination
    [("Downloads", "/downloads/", "link"), ("Downloads", "/downloads/mac/", "link")],
    [("Downloads", "/downloads/", "link"), ("Get Python", "/downloads/", "link")],
    [("Downloads", "/downloads/", "link"), ("Downloads", "/downloads/", "button")],
])
def test_different_targets_are_never_pooled(monkeypatch, key, controls):
    monkeypatch.setattr(jev, "post_json", split_reply({"1": 0.5, "2": 0.5}, "2"))
    d = jev.choose(duplicates(*controls), "goal", [])
    assert d["choice"] == "e2" and d["target_confidence"] == 0.0


def test_the_guard_layout_still_carries_href_at_index_14():
    source = camofox.READ_STATE
    body = source[source.index("cache.guard=e=>{"):]
    fields = body[body.index("return [") + len("return ["):body.index("];")]
    depth, parts, part = 0, [], ""
    for char in fields:
        depth += char in "([{" and 1 or char in ")]}" and -1 or 0
        if char == "," and depth == 0:
            parts.append(part.strip())
            part = ""
        else:
            part += char
    parts.append(part.strip())
    assert parts[jev.GUARD_HREF] == "e.getAttribute('href')"


def test_recent_actions_tell_jev_which_page_each_action_was_on(monkeypatch, key):
    post = goal_reply("CLICK", 0.5)
    monkeypatch.setattr(jev, "post_json", post)
    history = [{"action": "42 comments", "kind": "click", "text": None, "page_changed": True, "confidence": 0.9,
                "from_url": "https://news.example.test/", "url_after": "https://news.example.test/item?id=1"}]
    jev.choose(make_state(), "open the comments", history)
    # Named so Jev cannot read the page an action ran on as the page it led to.
    assert post.bodies[0]["state"]["recent_actions"] == [
        {"action": "42 comments", "kind": "click", "text": None, "page_changed": True,
         "from_url": "https://news.example.test/", "url_after": "https://news.example.test/item?id=1"}]


def test_token_usage_is_totalled_per_model_for_the_task(monkeypatch, key):
    from jev_browser.budget import Budget, current
    replies = iter([
        Response(200, {"model": "typesafe/jev-1.13", "answers": {}, "usage": {"input_tokens": 300, "output_tokens": 20}}),
        Response(200, {"model": "typesafe/jev-1.13", "answers": {}, "usage": {"input_tokens": 100, "output_tokens": 5}}),
        Response(200, {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 7, "cost": 0.001}}),
        Response(200, {"answers": {}, "usage": {"input_tokens": "lots", "output_tokens": -1}}),
    ])
    monkeypatch.setattr(jev._HTTP, "post", lambda *a, **k: next(replies))
    token = current.set(Budget(10, 30))
    try:
        for model in ("~typesafe/jev-latest", "~typesafe/jev-latest", "text-helper", "other"):
            jev.post_json("https://x.test", {"model": model})
        assert current.get().usage_summary() == {
            "input_tokens": 450, "output_tokens": 32, "cost": 0.001,
            "by_model": {"typesafe/jev-1.13": {"input_tokens": 400, "output_tokens": 25},
                         "text-helper": {"input_tokens": 50, "output_tokens": 7, "cost": 0.001}}}
    finally:
        current.reset(token)

